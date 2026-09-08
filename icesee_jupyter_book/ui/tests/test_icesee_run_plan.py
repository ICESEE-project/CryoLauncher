"""ICESEE Run Plan parity (Phase 5): the same semantic separation
CryoLauncher uses (execution mode / compute backend / model environment),
reusing CryoLauncher's own shared build_run_plan_panel composition -- with
ICESEE's DA identity (DAIdentity.summary_rows()) as first-class rows
underneath, not flattened into a generic single-model run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_GW = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"


def test_gateway_reuses_the_shared_run_plan_panel():
    src = _GW.read_text()
    assert (
        "from cryostack_src.frontend.cryolauncher.panels.run_plan import "
        "build_run_plan_panel" in src
    )
    assert "build_run_plan_panel(" in src
    assert "da_identity_from_params" in src
    assert "identity.summary_rows()" in src
    # no second, independent Run Plan implementation
    assert "class RunPlanPanel" not in src


def _build(monkeypatch, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", f"{user}-svc")
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui
    return build_icesee_ui()


def _find_run_plan_summary_html(page):
    """The Run Plan card's summary HTML is the one containing 'Execution
    mode' -- find it by content since it has no unique CSS hook."""
    found = []

    def walk(w):
        if isinstance(w, W.HTML) and "Execution mode" in (w.value or ""):
            found.append(w)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    return found[0] if found else None


def test_run_plan_shows_execution_semantics_and_da_identity(monkeypatch):
    page = _build(monkeypatch, user="run-plan-user")
    summary = _find_run_plan_summary_html(page)
    assert summary is not None, "Run Plan summary card not found"
    assert "Execution mode" in summary.value
    assert "Compute backend" in summary.value
    assert "Model environment" in summary.value
    # DA identity rows for the default example are present too (not a
    # generic single-model run) -- Forecast model is always shown when
    # DAIdentity resolves one from the loaded example.
    assert "Assimilation filter" in summary.value or "Forecast model" in summary.value


def test_run_plan_updates_when_the_mode_tab_changes(monkeypatch):
    page = _build(monkeypatch, user="run-plan-mode-user")
    summary = _find_run_plan_summary_html(page)

    def freevar(fn, name):
        idx = fn.__code__.co_freevars.index(name)
        return fn.__closure__[idx].cell_contents

    mode_tabs = None

    def walk(w):
        nonlocal mode_tabs
        if isinstance(w, W.Tab) and mode_tabs is None:
            mode_tabs = w
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    assert mode_tabs is not None
    assert "Local" in summary.value

    mode_tabs.selected_index = 2   # Cloud
    assert "Cloud" in summary.value
    assert "AWS Batch" in summary.value
