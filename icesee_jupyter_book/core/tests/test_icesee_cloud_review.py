"""ICESEE DA-aware Cloud Review (core/cloud_review.py).

Never forces ICESEE through cryostack_src.cloud.review's model/example/
run_target schema (SUPPORTED_CLOUD_MODELS does not include "icesee") --
this is the same SHAPE (review + launch gate + drift digest) with ICESEE's
own DA-shaped fields, reusing the shared review shell's rendering contract
(review_body.value / launch_button.disabled) without touching CryoLauncher's
own set_review_panel.

Launch readiness now has TWO independent real facts behind it:
* icesee_cloud_runtime_ready() -- a tested image is registered (image-level,
  True since the 2026-09-08 verification checkpoint);
* icesee_runtime_contract_ok()/review.runtime_contract_ok -- THIS run's own
  example + NP are inside what was actually verified (lorenz96 @ NP=1 only,
  see icesee_jupyter_book.core.cloud_runner's ICESEE_VERIFIED_EXAMPLES /
  ICESEE_VERIFIED_MAX_NP). Neither fact is ever faked or coerced.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.review import InfrastructureReadiness
from icesee_jupyter_book.core.cloud_review import (
    build_icesee_cloud_review,
    icesee_cloud_runtime_ready,
    icesee_runtime_contract_ok,
    render_icesee_review_panel,
)

_READY_INFRA = InfrastructureReadiness(
    account=True, storage=True, container=True, compute=True)


def test_icesee_cloud_runtime_is_honestly_ready_now():
    """A real, checkable fact: bkyanjo/icesee-combined:v1.0.1 was verified
    (2026-09-08) to run the Lorenz-96 example end-to-end under `with-icesee`
    and is registered in TESTED_IMAGES with "icesee" in its models tuple."""
    assert icesee_cloud_runtime_ready() is True


# ── the verified runtime contract (lorenz96 @ NP=1 only) ──────────────────
def test_lorenz96_at_np1_is_within_the_verified_contract():
    assert icesee_runtime_contract_ok(example_name="lorenz96", parallel_processes=1) is True


def test_np_greater_than_one_is_outside_the_verified_contract():
    assert icesee_runtime_contract_ok(example_name="lorenz96", parallel_processes=4) is False


def test_an_unverified_example_is_outside_the_contract_even_at_np1():
    assert icesee_runtime_contract_ok(example_name="issm", parallel_processes=1) is False


def test_review_launches_for_lorenz96_at_np1_once_infrastructure_is_ready():
    """Lorenz-96 + NP=1 -- the exact configuration verified 2026-09-08 --
    must become launchable once infra is ready. No other configuration may
    silently produce this result."""
    review = build_icesee_cloud_review(
        forecast_model="lorenz96", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=1, account_id="774888247882", region="us-east-2",
        infrastructure=_READY_INFRA, account_freshly_verified=True,
        example_name="lorenz96",
    )
    assert review.can_launch is True
    assert review.blocked_reasons == []
    assert review.icesee_runtime_ready is True
    assert review.runtime_contract_ok is True
    assert review.parallel_mode_label == "Single-rank verified"
    assert review.image_reference == "bkyanjo/icesee-combined:v1.0.1"


def test_np_greater_than_one_is_blocked_with_the_exact_reason():
    """NP>1 must never be silently coerced to NP=1 -- it is refused with a
    clear, honest reason, even though the image itself is tested-ready."""
    review = build_icesee_cloud_review(
        forecast_model="lorenz96", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=4, account_id="774888247882", region="us-east-2",
        infrastructure=_READY_INFRA, account_freshly_verified=True,
        example_name="lorenz96",
    )
    assert review.can_launch is False
    assert review.runtime_contract_ok is False
    assert any(
        "ICESEE_NP=4" in r and "not verified" in r and "single-rank" in r.lower()
        for r in review.blocked_reasons
    )
    assert "Unverified" in review.parallel_mode_label
    assert "NP=4" in review.parallel_mode_label


def test_unsupported_icesee_examples_remain_blocked():
    """An example besides lorenz96 must remain blocked even at NP=1 -- only
    lorenz96 has ever been run against this image."""
    review = build_icesee_cloud_review(
        forecast_model="issm", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=1, account_id="774888247882", region="us-east-2",
        infrastructure=_READY_INFRA, account_freshly_verified=True,
        example_name="issm",
    )
    assert review.can_launch is False
    assert review.runtime_contract_ok is False
    assert any(
        "issm" in r and "no verified cloud runtime path" in r
        for r in review.blocked_reasons
    )


def test_review_reports_every_real_blocking_reason_not_just_one():
    review = build_icesee_cloud_review(
        forecast_model="lorenz96", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=1, account_id="", region="us-east-2",
        infrastructure=InfrastructureReadiness(
            account=False, storage=False, container=False, compute=False,
        ),
        account_freshly_verified=False,
        example_name="lorenz96",
    )
    assert review.can_launch is False
    joined = " ".join(review.blocked_reasons)
    assert "AWS account connection" in joined
    assert "Storage" in joined
    assert "Compute" in joined
    # the tested-image gap is no longer one of the real blocking reasons --
    # icesee now has a verified tested image, so only infra gaps remain
    assert "tested cloud container" not in joined


def test_review_is_blocked_again_if_the_tested_image_were_ever_removed(monkeypatch):
    """Prove the gate is still driven by the real registry check, not a
    hardcoded True -- monkeypatch the ONE fact that would actually change."""
    import icesee_jupyter_book.core.cloud_review as cloud_review

    monkeypatch.setattr(cloud_review, "icesee_cloud_runtime_ready", lambda: False)

    review = build_icesee_cloud_review(
        forecast_model="lorenz96", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=1, account_id="774888247882", region="us-east-2",
        infrastructure=_READY_INFRA, account_freshly_verified=True,
        example_name="lorenz96",
    )
    assert review.can_launch is False
    assert any("tested cloud container" in r for r in review.blocked_reasons)
    assert review.icesee_runtime_ready is False
    assert review.image_reference == ""


def test_digest_changes_when_billable_config_changes():
    base = dict(
        forecast_model="lorenz96", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=1, account_id="774888247882", region="us-east-2",
        infrastructure=_READY_INFRA, account_freshly_verified=True,
        example_name="lorenz96",
    )
    r1 = build_icesee_cloud_review(**base)
    r2 = build_icesee_cloud_review(**{**base, "ensemble_size": 60})
    assert r1.digest != r2.digest


def test_digest_changes_when_the_example_changes_even_if_everything_else_matches():
    base = dict(
        forecast_model="lorenz96", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=1, account_id="774888247882", region="us-east-2",
        infrastructure=_READY_INFRA, account_freshly_verified=True,
    )
    r1 = build_icesee_cloud_review(**base, example_name="lorenz96")
    r2 = build_icesee_cloud_review(**base, example_name="issm")
    assert r1.digest != r2.digest


class _FakeWidgets:
    def __init__(self):
        class _W:
            value = ""
            disabled = False
        self.review_body = _W()
        self.launch_button = _W()


def test_render_disables_launch_when_infra_is_not_ready():
    review = build_icesee_cloud_review(
        forecast_model="lorenz96", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=1, account_id="774888247882", region="us-east-2",
        # compute deliberately not ready -- infra, not the tested image, is
        # the blocking reason here (icesee now has a real tested image)
        infrastructure=InfrastructureReadiness(
            account=True, storage=True, container=True, compute=False,
        ),
        account_freshly_verified=True,
        example_name="lorenz96",
    )
    widgets = _FakeWidgets()
    render_icesee_review_panel(widgets, review)
    assert widgets.launch_button.disabled is True
    assert "Forecast model" in widgets.review_body.value
    assert "lorenz96" in widgets.review_body.value
    assert "EnKF" in widgets.review_body.value
    assert "30" in widgets.review_body.value
    assert "Launch is blocked" in widgets.review_body.value


def test_render_disables_launch_for_np_greater_than_one_and_shows_unverified():
    review = build_icesee_cloud_review(
        forecast_model="lorenz96", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=4, account_id="774888247882", region="us-east-2",
        infrastructure=_READY_INFRA, account_freshly_verified=True,
        example_name="lorenz96",
    )
    widgets = _FakeWidgets()
    render_icesee_review_panel(widgets, review)
    assert widgets.launch_button.disabled is True
    assert "Not ready" in widgets.review_body.value      # ICESEE runtime row
    assert "Unverified" in widgets.review_body.value      # Parallel mode row
    assert "Launch is blocked" in widgets.review_body.value


def test_render_enables_launch_for_lorenz96_at_np1_and_shows_verified_wording():
    review = build_icesee_cloud_review(
        forecast_model="lorenz96", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=1, account_id="774888247882", region="us-east-2",
        infrastructure=_READY_INFRA, account_freshly_verified=True,
        example_name="lorenz96",
    )
    widgets = _FakeWidgets()
    render_icesee_review_panel(widgets, review)
    assert widgets.launch_button.disabled is False
    assert "bkyanjo/icesee-combined:v1.0.1" in widgets.review_body.value
    assert "ICESEE runtime" in widgets.review_body.value
    assert "Single-rank verified" in widgets.review_body.value
    assert "Parallel mode" in widgets.review_body.value
    assert "Processes" in widgets.review_body.value


def test_render_never_touches_cryolauncher_set_review_panel():
    """Static confirmation: this module owns its own renderer, it never
    imports or delegates to set_review_panel."""
    src = Path(__file__).resolve().parents[1].joinpath("cloud_review.py").read_text()
    assert "set_review_panel(" not in src   # never called -- only mentioned in prose
    assert "import CloudRunReview" not in src and "CloudRunReview(" not in src
