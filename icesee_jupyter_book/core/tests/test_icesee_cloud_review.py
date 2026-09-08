"""ICESEE DA-aware Cloud Review (core/cloud_review.py).

Never forces ICESEE through cryostack_src.cloud.review's model/example/
run_target schema (SUPPORTED_CLOUD_MODELS does not include "icesee") --
this is the same SHAPE (review + launch gate + drift digest) with ICESEE's
own DA-shaped fields, reusing the shared review shell's rendering contract
(review_body.value / launch_button.disabled) without touching CryoLauncher's
own set_review_panel.
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
    render_icesee_review_panel,
)


def test_icesee_cloud_runtime_is_honestly_ready_now():
    """A real, checkable fact: bkyanjo/icesee-combined:v1.0.1 was verified
    (2026-09-08) to run the Lorenz-96 example end-to-end under `with-icesee`
    and is registered in TESTED_IMAGES with "icesee" in its models tuple."""
    assert icesee_cloud_runtime_ready() is True


def test_review_launches_once_infrastructure_is_ready():
    review = build_icesee_cloud_review(
        forecast_model="lorenz96", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=8, account_id="774888247882", region="us-east-2",
        infrastructure=InfrastructureReadiness(
            account=True, storage=True, container=True, compute=True,
        ),
        account_freshly_verified=True,
    )
    assert review.can_launch is True
    assert review.blocked_reasons == []
    assert review.icesee_runtime_ready is True
    assert review.image_reference == "bkyanjo/icesee-combined:v1.0.1"


def test_review_reports_every_real_blocking_reason_not_just_one():
    review = build_icesee_cloud_review(
        forecast_model="lorenz96", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=8, account_id="", region="us-east-2",
        infrastructure=InfrastructureReadiness(
            account=False, storage=False, container=False, compute=False,
        ),
        account_freshly_verified=False,
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
        parallel_processes=8, account_id="774888247882", region="us-east-2",
        infrastructure=InfrastructureReadiness(
            account=True, storage=True, container=True, compute=True,
        ),
        account_freshly_verified=True,
    )
    assert review.can_launch is False
    assert any("tested cloud container" in r for r in review.blocked_reasons)
    assert review.icesee_runtime_ready is False
    assert review.image_reference == ""


def test_digest_changes_when_billable_config_changes():
    base = dict(
        forecast_model="lorenz96", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=8, account_id="774888247882", region="us-east-2",
        infrastructure=InfrastructureReadiness(True, True, True, True),
        account_freshly_verified=True,
    )
    r1 = build_icesee_cloud_review(**base)
    r2 = build_icesee_cloud_review(**{**base, "ensemble_size": 60})
    assert r1.digest != r2.digest


class _FakeWidgets:
    def __init__(self):
        class _W:
            value = ""
            disabled = False
        self.review_body = _W()
        self.launch_button = _W()


def test_render_disables_launch_when_blocked():
    review = build_icesee_cloud_review(
        forecast_model="lorenz96", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=8, account_id="774888247882", region="us-east-2",
        # compute deliberately not ready -- infra, not the tested image, is
        # the blocking reason here (icesee now has a real tested image)
        infrastructure=InfrastructureReadiness(
            account=True, storage=True, container=True, compute=False,
        ),
        account_freshly_verified=True,
    )
    widgets = _FakeWidgets()
    render_icesee_review_panel(widgets, review)
    assert widgets.launch_button.disabled is True
    assert "Forecast model" in widgets.review_body.value
    assert "lorenz96" in widgets.review_body.value
    assert "EnKF" in widgets.review_body.value
    assert "30" in widgets.review_body.value
    assert "Launch is blocked" in widgets.review_body.value


def test_render_enables_launch_when_everything_is_ready():
    review = build_icesee_cloud_review(
        forecast_model="lorenz96", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=8, account_id="774888247882", region="us-east-2",
        infrastructure=InfrastructureReadiness(True, True, True, True),
        account_freshly_verified=True,
    )
    widgets = _FakeWidgets()
    render_icesee_review_panel(widgets, review)
    assert widgets.launch_button.disabled is False
    assert "bkyanjo/icesee-combined:v1.0.1" in widgets.review_body.value


def test_render_never_touches_cryolauncher_set_review_panel():
    """Static confirmation: this module owns its own renderer, it never
    imports or delegates to set_review_panel."""
    src = Path(__file__).resolve().parents[1].joinpath("cloud_review.py").read_text()
    assert "set_review_panel(" not in src   # never called -- only mentioned in prose
    assert "import CloudRunReview" not in src and "CloudRunReview(" not in src
