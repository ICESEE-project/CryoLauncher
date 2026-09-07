"""C7.5 -- the CLOUD RUN active-run card + local elapsed/cost ticker."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.frontend.cryolauncher.cloud_active_run_runtime import (
    _hms,
    build_active_run_callbacks,
)
from cryostack_src.frontend.cryolauncher.cloud_environment import (
    build_cloud_environment_card,
)


class _Spawn:
    def __init__(self):
        self.q = []

    def __call__(self, coro):
        self.q.append(coro)

    def run(self):
        import asyncio

        while self.q:
            asyncio.run(self.q.pop(0))


def _bounded_sleep_factory(clock, cb_holder, max_ticks=4):
    """Fake sleep: advance the clock, and stop the ticker after a few ticks so
    the test loop terminates (the real ticker stops on a terminal state)."""
    n = {"i": 0}

    async def _sleep(_s):
        n["i"] += 1
        clock["t"] += 1.0
        if n["i"] >= max_ticks and cb_holder.get("cb") is not None:
            cb_holder["cb"].stop()

    return _sleep


@pytest.fixture
def card():
    return build_cloud_environment_card()


def _view(state, **over):
    v = dict(
        state=state, model="issm", example="SquareIceShelf",
        account_id="774888247882", region="us-east-2",
        vcpu=2, memory_gib=8, expected_runtime_minutes=5,
        cost_public={"available": True, "estimated_total_usd": 0.12,
                     "expected_runtime_minutes": 5},
        job_id="job-1", terminal=state in ("completed", "failed", "cancelled"),
    )
    v.update(over)
    return v


def _callbacks(card, clock, spawn, calls):
    holder = {}
    cb = build_active_run_callbacks(
        widgets=card,
        on_view_log=lambda: calls.append("log"),
        on_view_results=lambda: calls.append("results"),
        on_terminate=lambda: calls.append("terminate"),
        clock=lambda: clock["t"],
        sleep=_bounded_sleep_factory(clock, holder),
        spawn=spawn,
    )
    holder["cb"] = cb
    return cb


def test_hms_formats_elapsed():
    assert _hms(0) == "00:00"
    assert _hms(62) == "01:02"
    assert _hms(3723) == "01:02:03"


def test_card_appears_on_staging_and_shows_the_run_without_aws_plumbing(card):
    clock, spawn, calls = {"t": 0.0}, _Spawn(), []
    cb = _callbacks(card, clock, spawn, calls)
    cb.render(**_view("staging"))
    spawn.run()
    assert card.active_run_section.layout.display == "flex"
    blob = card.active_run_detail.value + card.active_run_status.value
    assert "774888247882" in blob and "2 vCPU" in blob
    # no ARNs / prefixes / queue / job-def on the primary surface
    for plumbing in ("job-queue", "job-definition", "arn:aws", "s3://", "ECR", "digest"):
        assert plumbing not in blob


def test_elapsed_and_cost_tick_locally_with_no_extra_aws_call(card):
    import re

    clock, spawn, calls = {"t": 100.0}, _Spawn(), []
    cb = _callbacks(card, clock, spawn, calls)
    cb.render(**_view("staging"))          # first render stamps started_at = 100
    clock["t"] = 100.0 + 155               # 2:35 later
    cb.render(**_view("running"))
    detail_at_155 = card.active_run_detail.value
    assert "Elapsed" in detail_at_155 and "02:35" in detail_at_155
    # live cost after 155s of a 5-min (300s) run == 0.12 * 155/300 ≈ $0.06
    assert "$0.06" in detail_at_155
    assert "Estimated cost so far" in detail_at_155 and "(estimate)" in detail_at_155

    spawn.run()                            # the bounded background tick loop
    detail_later = card.active_run_detail.value
    # elapsed advanced further, purely from the local clock
    m = re.search(r"(\d\d):(\d\d)", detail_later)
    assert m and (int(m.group(1)) * 60 + int(m.group(2))) > 155
    # the ticker never called the log/results/terminate handlers (no AWS)
    assert calls == []


def test_cost_shows_unavailable_when_the_launch_estimate_was_unavailable(card):
    clock, spawn, calls = {"t": 0.0}, _Spawn(), []
    cb = _callbacks(card, clock, spawn, calls)
    cb.render(**_view("running", cost_public={"available": False}))
    spawn.run()  # bounded
    assert "Unavailable" in card.active_run_detail.value


def test_terminal_state_hides_terminate_and_enables_results(card):
    clock, spawn, calls = {"t": 0.0}, _Spawn(), []
    cb = _callbacks(card, clock, spawn, calls)
    cb.render(**_view("running"))
    spawn.run()
    cb.render(**_view("completed"))
    assert card.active_run_terminate_button.layout.display == "none"
    assert card.active_run_results_button.disabled is False
    # elapsed / live-cost rows drop out on a terminal state
    assert "Estimated cost so far" not in card.active_run_detail.value


def test_failed_state_keeps_the_card_but_points_to_the_log(card):
    clock, spawn, calls = {"t": 0.0}, _Spawn(), []
    cb = _callbacks(card, clock, spawn, calls)
    cb.render(**_view("failed"))
    assert card.active_run_section.layout.display == "flex"
    assert "Failed" in card.active_run_status.value


def test_action_buttons_route_to_the_workspace_handlers(card):
    clock, spawn, calls = {"t": 0.0}, _Spawn(), []
    _callbacks(card, clock, spawn, calls)
    card.active_run_log_button.click()
    card.active_run_results_button.click()
    card.active_run_terminate_button.click()
    assert calls == ["log", "results", "terminate"]


def test_no_secret_or_external_id_on_the_active_run_surface(card):
    clock, spawn, calls = {"t": 0.0}, _Spawn(), []
    cb = _callbacks(card, clock, spawn, calls)
    cb.render(**_view("running"))
    spawn.run()
    blob = (card.active_run_detail.value + card.active_run_status.value
            + card.active_run_title.value)
    for forbidden in ("AWS_SECRET", "SESSION_TOKEN", "AWS_ACCESS_KEY_ID",
                      "ExternalId", "cryostack:774", "ASIA"):
        assert forbidden not in blob


# -- AWS diagnostics menu on the CLOUD RUN card (pure -- no AWS call) ----
_RES = {
    "region": "us-east-2", "account_id": "774888247882",
    "batch_job_id": "job-1", "job_queue": "cryostack-queue",
    "job_definition": "cryostack-icepack:3",
    "s3_run": "s3://cryostack-runs-774888247882/runs/alice/run-1",
    "log_stream": "cryostack-icepack/default/abc",
}


def test_diagnostics_menu_renders_from_the_view_snapshot(card):
    clock, spawn, calls = {"t": 0.0}, _Spawn(), []
    cb = _callbacks(card, clock, spawn, calls)
    cb.render(**_view("running", aws_resources=_RES))
    spawn.run()
    menu = card.active_run_diagnostics.value
    assert "AWS diagnostics" in menu
    for label in ("Batch job", "Container logs", "S3 run storage",
                  "Job queue", "Job definition"):
        assert f">{label}</a>" in menu
    assert "console.aws.amazon.com/batch/home" in menu
    assert 'target=\'_blank\'' in menu and "noopener" in menu


def test_diagnostics_menu_is_empty_until_a_resource_is_known(card):
    clock, spawn, calls = {"t": 0.0}, _Spawn(), []
    cb = _callbacks(card, clock, spawn, calls)
    cb.render(**_view("staging"))                 # no aws_resources yet
    spawn.run()
    assert card.active_run_diagnostics.value == ""


def test_diagnostics_menu_carries_no_credential_material(card):
    clock, spawn, calls = {"t": 0.0}, _Spawn(), []
    cb = _callbacks(card, clock, spawn, calls)
    poisoned = {**_RES, "AWS_SESSION_TOKEN": "FQoG", "ExternalId": "cryostack:alice:z"}
    cb.render(**_view("running", aws_resources=poisoned))
    spawn.run()
    menu = card.active_run_diagnostics.value
    for forbidden in ("FQoG", "SESSION_TOKEN", "ExternalId", "cryostack:alice"):
        assert forbidden not in menu
