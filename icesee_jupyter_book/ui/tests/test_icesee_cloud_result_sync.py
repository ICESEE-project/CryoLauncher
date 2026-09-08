"""ICESEE Cloud result synchronization (item 4 of the ICESEE cloud
execution-parity checkpoint): selecting a finished/running CLOUD run in the
Workspace Runs panel syncs s3://<s3_run>/outputs/ into that run's own
workspace_directory BEFORE the existing Results preview / DA-aware
ResultPackage summary runs -- resolved from the run's OWN persisted
metadata['aws_resources'], never the live Cloud panel widgets. A LOCAL run
never triggers any AWS call. No real AWS CLI is ever invoked.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_GW = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"


def test_gateway_wires_the_sync_step_into_run_selection():
    src = _GW.read_text()
    assert "sync_icesee_cloud_results" in src
    assert "_sync_icesee_cloud_run_results(run)" in src


def _build_gateway(monkeypatch, tmp_path, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", f"{user}-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui
    return build_icesee_ui()


def _find_runs_select(page):
    found = {}

    def walk(w):
        if "runs" not in found:
            notifiers = getattr(w, "_trait_notifiers", None)
            if notifiers and "value" in notifiers:
                for handlers in notifiers["value"].values():
                    for h in handlers:
                        if getattr(h, "__name__", "") == "show_selection":
                            found["runs"] = (w, h)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    return found.get("runs")


def _freevar(fn, name):
    idx = fn.__code__.co_freevars.index(name)
    return fn.__closure__[idx].cell_contents


class _FakeCompleted:
    def __init__(self, stdout):
        self.returncode, self.stdout, self.stderr = 0, stdout, ""


def test_selecting_a_cloud_run_syncs_from_its_own_persisted_s3_identity(
    monkeypatch, tmp_path,
):
    calls = []

    class _FakeSubprocess:
        @staticmethod
        def run(argv, **kwargs):
            calls.append({"argv": argv, "env": kwargs.get("env")})
            return _FakeCompleted("")

    import cryostack_src.cloud.legacy.aws_batch as legacy_batch
    monkeypatch.setattr(legacy_batch, "subprocess", _FakeSubprocess)

    from cryostack_src.workspace import user_run_root
    from icesee_jupyter_book.core import run_records as rr

    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "sync-select-user")
    root = user_run_root(app="icesee")
    run_dir = root / "cloud-run-1"
    rr.record_run(
        run_dir=run_dir, run_id="cloud-run-1", name="cloud run",
        params={}, example="lorenz96", execution_mode="cloud", backend="aws",
        status="running", jobid="job-abc",
        remote_directory="s3://bucket/runs/cloud-run-1",
    )
    rr.update_run(run_dir, extra_metadata={"aws_resources": {
        "region": "eu-west-1", "s3_run": "s3://bucket/runs/cloud-run-1",
        "batch_job_id": "job-abc",
    }})

    page = _build_gateway(monkeypatch, tmp_path, user="sync-select-user")
    runs_select, show_selection = _find_runs_select(page)
    assert runs_select is not None

    runs_select.value = "cloud-run-1"   # triggers show_selection -> on_run_selected

    assert calls, "no S3 sync was attempted for a cloud run"
    sync_call = calls[0]
    assert sync_call["argv"] == [
        "aws", "--region", "eu-west-1", "s3", "sync",
        "s3://bucket/runs/cloud-run-1/outputs/", str(run_dir.resolve()),
    ]


def test_selecting_a_local_run_never_triggers_an_aws_call(monkeypatch, tmp_path):
    calls = []

    class _FakeSubprocess:
        @staticmethod
        def run(argv, **kwargs):
            calls.append(argv)
            return _FakeCompleted("")

    import cryostack_src.cloud.legacy.aws_batch as legacy_batch
    monkeypatch.setattr(legacy_batch, "subprocess", _FakeSubprocess)

    from cryostack_src.workspace import user_run_root
    from icesee_jupyter_book.core import run_records as rr

    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "sync-local-user")
    root = user_run_root(app="icesee")
    run_dir = root / "local-run-1"
    rr.record_run(
        run_dir=run_dir, run_id="local-run-1", name="local run",
        params={}, example="lorenz96", execution_mode="local", backend="local",
        status="done",
    )

    page = _build_gateway(monkeypatch, tmp_path, user="sync-local-user")
    runs_select, _ = _find_runs_select(page)
    runs_select.value = "local-run-1"

    assert calls == []
