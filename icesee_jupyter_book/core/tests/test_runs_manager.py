"""IceseeRunsManager: the thin adapter that lets ICESEE reuse the shared
CryoLauncher Workspace history panel without re-implementing WorkspaceManager.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.core import run_records as rr
from icesee_jupyter_book.core.runs_manager import IceseeRunsManager

_PARAMS = {
    "modeling-parameters": {"example_name": "lorenz96"},
    "enkf-parameters": {"model_name": "lorenz", "filter_type": "EnKF", "Nens": 20},
}


def _make_run(root: Path, run_id: str, *, status="done"):
    run_dir = root / run_id
    return rr.record_run(
        run_dir=run_dir, run_id=run_id, name=f"ICESEE run {run_id}",
        params=_PARAMS, example="lorenz96", execution_mode="local",
        backend="local", status=status,
    )


def test_refresh_list_select_round_trip(tmp_path):
    _make_run(tmp_path, "run-a")
    _make_run(tmp_path, "run-b")
    mgr = IceseeRunsManager(root=tmp_path)

    runs = mgr.refresh()
    assert {r.id for r in runs} == {"run-a", "run-b"}
    assert mgr.selected_run() is None

    selected = mgr.select_run("run-a")
    assert selected is not None and selected.id == "run-a"
    assert mgr.selected_run().id == "run-a"
    assert mgr.reconcile_run("run-a").id == "run-a"


def test_files_lists_the_runs_local_workspace(tmp_path):
    _make_run(tmp_path, "run-a")
    (tmp_path / "run-a" / "notes.txt").write_text("hi")
    mgr = IceseeRunsManager(root=tmp_path)
    mgr.refresh()

    names = {p.name for p in mgr.files("run-a")}
    assert "notes.txt" in names
    assert ".cryostack-run.json" in names


def test_tail_reads_a_persisted_run_log_or_reports_absence(tmp_path):
    _make_run(tmp_path, "run-a")
    mgr = IceseeRunsManager(root=tmp_path)
    mgr.refresh()
    assert "no local log captured" in mgr.tail("run-a")

    (tmp_path / "run-a" / "run.log").write_text("line one\nline two\n")
    mgr.refresh()
    assert mgr.tail("run-a") == "line one\nline two\n"


def test_download_results_zips_only_when_outputs_exist(tmp_path):
    _make_run(tmp_path, "run-a")
    mgr = IceseeRunsManager(root=tmp_path)
    mgr.refresh()

    assert mgr.download_results("run-a") is None    # no results/ directory yet

    (tmp_path / "run-a" / "results").mkdir()
    (tmp_path / "run-a" / "results" / "state.h5").write_bytes(b"x")
    mgr.refresh()
    zip_path = mgr.download_results("run-a")
    assert zip_path is not None and zip_path.is_file()
    assert zip_path.name == "results_bundle.zip"


def test_delete_run_removes_the_workspace_and_forgets_the_run(tmp_path):
    _make_run(tmp_path, "run-a")
    mgr = IceseeRunsManager(root=tmp_path)
    mgr.refresh()
    mgr.select_run("run-a")

    assert mgr.delete_run("run-a") is True
    assert not (tmp_path / "run-a").exists()
    assert mgr.selected_run() is None
    assert mgr.select_run("run-a") is None


def test_delete_run_refuses_a_workspace_outside_the_managed_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    run = _make_run(outside, "escaped-run")
    mgr = IceseeRunsManager(root=tmp_path / "managed")
    (tmp_path / "managed").mkdir()
    mgr._runs = {"escaped-run": run}     # simulate a stale/forged entry

    assert mgr.delete_run("escaped-run") is False
    assert (outside / "escaped-run").exists()
