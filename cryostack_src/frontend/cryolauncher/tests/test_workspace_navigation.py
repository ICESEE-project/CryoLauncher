"""Workspace tab navigation: Runs is the selection/control surface; Files /
Run Log / Results are views of the SAME selected run.

Guards:
* Tail Log switches the existing Workspace Tab to Run Log; Figures -> Results;
  Download does not change tabs;
* the selected run is shared state -- switching runs never shows stale content;
* no second Run Log / Results panel, viewer, or result-loading path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.frontend.cryolauncher.workspace.run_details import (
    build_run_details,
)
from cryostack_src.frontend.cryolauncher.workspace.run_history import (
    build_workspace_history_panel,
)


class _Run:
    def __init__(self, rid, model="issm"):
        self.id = rid
        self.model = model
        self.backend = "spack"
        self.execution_mode = "remote"
        self.status = "completed"
        self.jobid = f"job-{rid}"
        from datetime import datetime
        self.created = datetime(2026, 1, 1, 12, 0)
        self.workspace_directory = None
        self.remote_directory = None
        self.log_file = None
        self.metadata = {}
        self.container = {}
        self.software = {}


class _FakeManager:
    def __init__(self, runs):
        self._runs = {r.id: r for r in runs}
        self._sel = None
        self.calls = []

    def refresh(self):
        return list(self._runs.values())

    def list_runs(self):
        return list(self._runs.values())

    def selected_run(self):
        return self._runs.get(self._sel or "")

    def select_run(self, rid):
        self._sel = rid if rid in self._runs else None
        self.calls.append(("select", rid))
        return self._runs.get(self._sel or "")

    def reconcile_run(self, rid):
        return self._runs.get(rid)

    def files(self, rid):
        return []

    def tail(self, rid):
        self.calls.append(("tail", rid))

    def download_results(self, rid=None):
        self.calls.append(("download", rid))

    def download_figures(self, rid=None):
        self.calls.append(("download_figures", rid))

    def delete_run(self, rid):
        return False


def _wire(mgr, tab):
    """Reproduce the gateway's Runs-tab action routing over a real Tab."""
    LOG, RESULTS = 2, 3
    preview_calls, download_calls = [], []

    def on_tail_log():
        rid = panel.runs.value
        mgr.select_run(rid)
        tab.selected_index = LOG
        mgr.tail(rid)

    def on_show_figures():
        rid = panel.runs.value
        mgr.select_run(rid)
        tab.selected_index = RESULTS
        preview_calls.append(rid)

    def on_download():
        rid = panel.runs.value
        mgr.select_run(rid)
        download_calls.append(rid)          # NO tab change

    panel = build_workspace_history_panel(
        manager=mgr, defer_initial_load=False,
        on_tail_log=on_tail_log, on_show_figures=on_show_figures,
        on_download=on_download,
    )
    return panel, preview_calls, download_calls


def _tab():
    return W.Tab(children=[W.HTML(), W.HTML(), W.HTML(), W.HTML()])


# ── navigation ─────────────────────────────────────────────────────────
def test_run_details_tab_order_is_canonical():
    d = build_run_details(
        log_output=W.Output(), results_output=W.Output(),
        download_controls=W.HTML(), log_controls=W.HTML(),
        runs_panel=W.HTML(), files_panel=W.HTML(),
    )
    titles = [d.tabs.get_title(i) for i in range(len(d.tabs.children))]
    assert titles == ["Runs", "Files", "Run Log", "Results"]


def test_tail_log_switches_to_run_log_tab():
    mgr = _FakeManager([_Run("A")])
    tab = _tab()
    panel, _, _ = _wire(mgr, tab)
    tab.selected_index = 0
    panel.tail_button.click()
    assert tab.selected_index == 2
    assert ("tail", "A") in mgr.calls


def test_figures_switches_to_results_tab():
    mgr = _FakeManager([_Run("A")])
    tab = _tab()
    panel, preview_calls, _ = _wire(mgr, tab)
    tab.selected_index = 0
    panel.figures_button.click()
    assert tab.selected_index == 3
    assert preview_calls == ["A"]


def test_download_does_not_change_tabs():
    mgr = _FakeManager([_Run("A")])
    tab = _tab()
    panel, _, download_calls = _wire(mgr, tab)
    tab.selected_index = 0
    panel.download_button.click()
    assert tab.selected_index == 0
    assert download_calls == ["A"]
    assert not any(c[0] == "download_figures" for c in mgr.calls)


def test_direct_tab_click_still_works():
    tab = _tab()
    tab.selected_index = 1
    assert tab.selected_index == 1
    tab.selected_index = 3
    assert tab.selected_index == 3


# ── shared selected run / no stale content ─────────────────────────────
def test_selected_run_is_preserved_by_tail_and_figures():
    mgr = _FakeManager([_Run("A"), _Run("B")])
    tab = _tab()
    panel, preview_calls, _ = _wire(mgr, tab)
    panel.runs.value = "A"
    panel.tail_button.click()
    assert mgr.selected_run().id == "A" and ("tail", "A") in mgr.calls
    panel.figures_button.click()
    assert mgr.selected_run().id == "A" and preview_calls[-1] == "A"


def test_switching_runs_loads_new_run_not_stale():
    mgr = _FakeManager([_Run("A"), _Run("B")])
    tab = _tab()
    panel, preview_calls, _ = _wire(mgr, tab)
    panel.runs.value = "A"
    panel.tail_button.click()
    panel.runs.value = "B"
    panel.tail_button.click()
    assert tab.selected_index == 2
    assert mgr.calls[-2:] == [("select", "B"), ("tail", "B")]
    panel.figures_button.click()
    assert mgr.selected_run().id == "B" and preview_calls[-1] == "B"


# ── architecture: no duplicate panels / viewers / loaders ──────────────
def test_no_duplicate_log_or_results_viewer():
    d = build_run_details(
        log_output=W.Output(), results_output=W.Output(),
        download_controls=W.HTML(), log_controls=W.HTML(),
        runs_panel=W.HTML(), files_panel=W.HTML(),
    )
    tabs = [w for w in _iter(d.container) if isinstance(w, W.Tab)]
    assert len(tabs) == 1                       # ONE Workspace Tab
    assert len(tabs[0].children) == 4           # exactly Runs/Files/Run Log/Results


def test_history_panel_falls_back_without_callbacks():
    mgr = _FakeManager([_Run("A")])
    panel = build_workspace_history_panel(manager=mgr, defer_initial_load=False)
    panel.runs.value = "A"
    panel.tail_button.click()
    assert ("tail", "A") in mgr.calls           # manager tail, unchanged behaviour


def _iter(w):
    yield w
    for c in getattr(w, "children", ()):
        yield from _iter(c)


def test_history_card_shows_aws_diagnostics_from_the_run_s_own_persisted_resources():
    """A historical cloud run's AWS diagnostics menu is built from ITS OWN
    metadata['aws_resources'] -- never the current Cloud Environment defaults,
    and never an AWS call."""
    run = _Run("cloud-1", model="icepack")
    run.backend, run.execution_mode = "aws", "cloud"
    run.metadata = {"aws_resources": {
        "region": "eu-west-1",                      # a DIFFERENT region than any default
        "batch_job_id": "old-job-xyz",
        "s3_run": "s3://old-bucket/runs/bob/r0",
        "job_queue": "cryostack-queue",
    }}
    mgr = _FakeManager([run])
    panel = build_workspace_history_panel(manager=mgr, defer_initial_load=False)
    panel.runs.value = "cloud-1"

    selected = next(w for w in _iter(panel.runs_panel)
                    if isinstance(w, W.HTML) and "Selected Run" not in w.value
                    and "cryostack-selected-run-card" in w.value)
    html = selected.value
    assert "AWS diagnostics" in html
    assert "eu-west-1" in html and "old-job-xyz" in html
    assert "us-east-2" not in html                  # no leakage of a current default
    assert "Backend</span><b>AWS Batch (Fargate)" in html
