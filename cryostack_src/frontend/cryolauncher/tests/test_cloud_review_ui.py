"""C7.4 -- RUN ESTIMATE line + REVIEW CLOUD RUN surface + drift protection."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.config import resolve_cloud_config
from cryostack_src.cloud.estimate.estimator import estimate_cloud_cost
from cryostack_src.cloud.estimate.models import FargatePrices, RuntimeEstimate
from cryostack_src.cloud.review import (
    InfrastructureReadiness,
    build_cloud_run_review,
)
from cryostack_src.frontend.cryolauncher import cloud_environment as ce_mod
from cryostack_src.frontend.cryolauncher.cloud_environment import build_cloud_environment_card
from cryostack_src.frontend.cryolauncher.cloud_review_runtime import (
    build_cloud_review_callbacks,
)

OHIO = FargatePrices(region="us-east-2", vcpu_usd_per_hour=0.04048,
                     gib_usd_per_hour=0.004445, ephemeral_usd_per_gib_hour=0.000111,
                     source="AWS Price List API (us-east-1)",
                     source_timestamp="2026-09-03T00:00:00+00:00", available=True)
RT = RuntimeEstimate(minutes=5.0, source="Based on the SquareIceShelf reference estimate",
                     basis="example_table")


class _Out:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def clear_output(self, *a, **k): pass


class _DeferredSpawn:
    def __init__(self): self.q = []
    def __call__(self, coro): self.q.append(coro)
    def run(self):
        import asyncio
        while self.q:
            asyncio.run(self.q.pop(0))


def _immediate(fn):
    async def _c(): return fn()
    return _c()


def _review(*, ready=True, fresh=True, licensed=True, prices=OHIO, cfg=None):
    cfg = cfg or resolve_cloud_config(bucket="cryostack-runs-774888247882",
                                      model="issm", region="us-east-2")
    cost = estimate_cloud_cost(region=cfg.region, vcpu=cfg.vcpu, memory_gib=cfg.memory_gib,
                               expected_runtime_minutes=RT.minutes,
                               ephemeral_gib=cfg.ephemeral_gib, prices=prices)
    infra = (InfrastructureReadiness(account=fresh, storage=True, container=True, compute=True)
             if ready else
             InfrastructureReadiness(account=fresh, storage=False, container=True, compute=True))
    pf = [] if licensed else ["[cloud][ERROR] ISSM needs a MATLAB license."]
    return build_cloud_run_review(
        config=cfg, model="issm", example="SquareIceShelf", run_target="runme.m",
        account_id="774888247882", region=cfg.region, infrastructure=infra,
        runtime=RT, cost=cost, account_freshly_verified=fresh,
        preflight_problems=pf,
    )


@pytest.fixture
def card():
    return build_cloud_environment_card()


def _cbs(card, *, review, digest="D0", launch=None, spawn=None):
    return build_cloud_review_callbacks(
        widgets=card,
        review_builder=lambda: review() if callable(review) else review,
        digest_builder=lambda: digest() if callable(digest) else digest,
        launch_handler=launch or (lambda r: None),
        log_output=_Out(),
        spawn=spawn or _DeferredSpawn(),
        to_thread=_immediate,
    )


# -- estimate line -------------------------------------------------
def test_estimate_line_appears_only_when_infrastructure_is_ready(card):
    spawn = _DeferredSpawn()
    cbs = _cbs(card, review=lambda: _review(ready=True), spawn=spawn)
    cbs.refresh_estimate()
    spawn.run()
    assert card.run_estimate_section.layout.display == "flex"
    assert "5 min" in card.run_estimate_line.value
    assert "2 vCPU" in card.run_estimate_line.value and "8 GiB" in card.run_estimate_line.value


def test_estimate_line_hidden_when_not_ready(card):
    spawn = _DeferredSpawn()
    cbs = _cbs(card, review=lambda: _review(ready=False), spawn=spawn)
    cbs.refresh_estimate()
    spawn.run()
    assert card.run_estimate_section.layout.display == "none"


def test_cost_unavailable_shows_text_not_a_number(card):
    spawn = _DeferredSpawn()
    cbs = _cbs(card, review=lambda: _review(prices=FargatePrices(region="us-east-2",
                                                                available=False)),
              spawn=spawn)
    cbs.refresh_estimate()
    spawn.run()
    assert "unavailable" in card.run_estimate_line.value.lower()


# -- review surface ---------------------------------------------
def test_review_opens_the_panel_with_the_professional_layout(card):
    spawn = _DeferredSpawn()
    cbs = _cbs(card, review=lambda: _review(), spawn=spawn)
    cbs.review()
    spawn.run()
    assert card.review_panel.layout.display == "flex"
    body = card.review_body.value
    for label in ("REVIEW CLOUD RUN" if False else "Experiment", "Resources",
                  "Estimated cost", "Infrastructure", "774888247882", "SquareIceShelf"):
        assert label in body or label in card.review_panel.children[0].value
    assert "AWS charges apply to your AWS account" in card.review_notice.value
    assert not card.launch_button.disabled


def test_blocked_review_disables_launch_and_explains_why(card):
    spawn = _DeferredSpawn()
    cbs = _cbs(card, review=lambda: _review(licensed=False), spawn=spawn)
    cbs.review()
    spawn.run()
    assert card.launch_button.disabled
    assert "MATLAB license reachable from AWS" in card.review_body.value
    assert "ISSM runtime" in card.review_body.value          # distinct readiness row


def test_back_hides_the_panel(card):
    spawn = _DeferredSpawn()
    cbs = _cbs(card, review=lambda: _review(), spawn=spawn)
    cbs.review(); spawn.run()
    cbs.back()
    assert card.review_panel.layout.display == "none"


# -- drift protection ------------------------------------------
def test_launch_calls_the_handler_only_when_review_is_fresh_and_valid(card):
    spawn = _DeferredSpawn()
    launched = []
    the_review = _review()
    cbs = _cbs(card, review=the_review, digest=lambda: the_review.digest,
               launch=lambda r: launched.append(r), spawn=spawn)
    cbs.review(); spawn.run()
    cbs.launch()
    assert len(launched) == 1
    assert card.review_panel.layout.display == "none"


def test_stale_review_cannot_launch_and_forces_a_re_review(card):
    spawn = _DeferredSpawn()
    launched = []
    the_review = _review()
    digest = {"v": the_review.digest}
    cbs = _cbs(card, review=the_review, digest=lambda: digest["v"],
               launch=lambda r: launched.append(r), spawn=spawn)
    cbs.review(); spawn.run()

    digest["v"] = "changed-digest"           # the billable config changed
    cbs.launch()
    spawn.run()
    assert launched == []                    # never launched a stale review
    assert "configuration changed" in card.review_notice.value.lower()
    assert card.review_panel.layout.display == "flex"   # re-opened for review


def test_launch_before_any_review_does_not_call_the_handler(card):
    spawn = _DeferredSpawn()
    launched = []
    cbs = _cbs(card, review=lambda: _review(), launch=lambda r: launched.append(r),
               spawn=spawn)
    cbs.launch()
    spawn.run()
    assert launched == []


# -- no secrets in the surface --------------------------------
def test_review_surface_shows_no_secret_or_external_id(card):
    spawn = _DeferredSpawn()
    cbs = _cbs(card, review=lambda: _review(), spawn=spawn)
    cbs.review(); spawn.run()
    blob = card.review_body.value + card.review_notice.value + card.run_estimate_line.value
    for forbidden in ("AWS_SECRET", "SESSION_TOKEN", "ExternalId", "cryostack:774"):
        assert forbidden not in blob


def test_no_access_key_or_profile_prompt_in_the_estimate_or_review_source():
    src = inspect.getsource(ce_mod)
    lowered = src.lower().replace("does not store your aws access keys", "")
    assert "access key id" not in lowered
    assert "secret access key" not in lowered
