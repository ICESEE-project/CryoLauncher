# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher active cloud-run surface
# File        : cloud_active_run_runtime.py
#
# Description :
#     Renders the compact CLOUD RUN status card and ticks a local elapsed /
#     estimated-cost display. No AWS call is made here -- state changes come
#     from CloudRunController.on_run_view, elapsed time is local wall clock,
#     and live cost reuses the C7.4 estimate retained at launch.
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from cryostack_src.cloud.estimate import format_usd, live_cost_usd
from cryostack_src.frontend.cryolauncher.cloud_environment import (
    set_active_run_view,
    show_active_run,
)
from cryostack_src.frontend.cryolauncher.cloud_run_controller import is_terminal
from cryostack_src.frontend.cryolauncher.cloud_runtime import _spawn

_RUNNING = ("staging", "submitting", "queued", "running")


def _hms(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def _minutes_label(minutes: float) -> str:
    m = float(minutes or 0)
    if m <= 0:
        return "—"
    return f"~{m:.0f} min" if m >= 1 else f"~{m:.1f} min"


@dataclass
class ActiveRunCallbacks:
    render: Callable          # (**view) -> None  -- bound to controller.on_run_view
    stop: Callable            # tear down the ticker (kernel shutdown / new run)


def build_active_run_callbacks(
    *,
    widgets,
    on_view_log: Callable,
    on_view_results: Callable,
    on_terminate: Callable,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], object] = asyncio.sleep,
    spawn: Callable = _spawn,
) -> ActiveRunCallbacks:
    """Wire the CLOUD RUN card. ``clock`` is monotonic wall time (local, no AWS)."""

    _state: dict = {"started_at": 0.0, "ticking": False, "view": {}, "gen": 0}

    widgets.active_run_log_button.on_click(lambda _=None: on_view_log())
    widgets.active_run_results_button.on_click(lambda _=None: on_view_results())
    widgets.active_run_terminate_button.on_click(lambda _=None: on_terminate())

    def _resource_text(v: dict) -> str:
        vcpu = v.get("vcpu") or 0
        mem = v.get("memory_gib") or 0
        if vcpu and mem:
            return f"{vcpu:g} vCPU · {mem:g} GiB"
        return "—"

    def _paint() -> None:
        v = _state["view"]
        if not v:
            return
        started = _state["started_at"]
        elapsed = max(0.0, clock() - started) if started else 0.0
        cost = live_cost_usd(v.get("cost_public") or {}, elapsed)
        cost_text = "Unavailable" if cost is None else format_usd(cost)
        set_active_run_view(
            widgets,
            model=v.get("model", ""), example=v.get("example", ""),
            state=v.get("state", ""), account_id=v.get("account_id", ""),
            region=v.get("region", ""), resource_text=_resource_text(v),
            elapsed_text=_hms(elapsed), cost_text=cost_text,
            expected_text=_minutes_label(v.get("expected_runtime_minutes")),
            image_reference=v.get("image_reference", ""),
            image_digest=v.get("image_digest", ""),
            image_label=v.get("image_label", ""),
        )

    async def _tick_loop(gen: int) -> None:
        # elapsed + live cost update once a second -- purely local, never an
        # AWS call. AWS status polling keeps its own (much slower) cadence.
        while (
            _state["ticking"]
            and _state["gen"] == gen
            and not is_terminal(_state["view"].get("state", ""))
        ):
            _paint()
            await sleep(1.0)
        _paint()

    def render(**view) -> None:
        state = view.get("state", "")
        _state["view"] = view
        if state == "staging" and not _state["started_at"]:
            _state["started_at"] = clock()
        # a brand-new run (staging again after a terminal one) resets the clock
        if state == "staging" and is_terminal(
            _prev_state := _state.get("_prev", "")
        ):
            _state["started_at"] = clock()
        _state["_prev"] = state

        show_active_run(widgets, True)
        _paint()

        running = state in _RUNNING
        if running and not _state["ticking"]:
            _state["ticking"] = True
            _state["gen"] += 1
            spawn(_tick_loop(_state["gen"]))
        elif is_terminal(state):
            _state["ticking"] = False

    def stop() -> None:
        _state["ticking"] = False

    return ActiveRunCallbacks(render=render, stop=stop)
