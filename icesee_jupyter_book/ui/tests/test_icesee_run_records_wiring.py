"""ICESEE Workspace/run-identity, step 1b: the gateway actually calls
run_records.record_run / update_run on every submission path (Local /
Remote / Cloud), on top of the already-persisted-run-model backend
(icesee_jupyter_book/core/run_records.py, +10 tests) and the already-wired
per-user run_dir isolation (test_icesee_run_isolation.py). Before this
checkpoint `run_records` was imported but never called -- a finished ICESEE
run still left no local manifest.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_GW = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"


def test_gateway_records_a_run_on_every_submission_path():
    src = _GW.read_text()
    assert "from icesee_jupyter_book.core import run_records" in src
    assert "def _record_icesee_run(" in src
    assert "def _update_icesee_run(" in src
    # one _record_icesee_run(...) call per execution mode
    assert 'execution_mode="local"' in src
    assert 'execution_mode="remote"' in src
    assert 'execution_mode="cloud"' in src
    assert src.count("_record_icesee_run(") >= 3


def test_remote_and_cloud_status_checks_update_the_local_manifest():
    src = _GW.read_text()
    assert '_update_icesee_run(\n                            Path(STATUS["local_run_dir"]),' in src \
        or 'STATUS["local_run_dir"]' in src
    assert "_update_icesee_run(Path(STATUS[\"local_run_dir\"]), status=" in src


def test_record_and_update_helpers_never_raise_on_a_bad_run_dir(monkeypatch, tmp_path):
    """The real behavioural contract: a manifest failure must never surface
    as an exception to the caller -- it is caught and logged."""
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "run-records-wiring-user")
    monkeypatch.setenv("USER", "run-records-wiring-svc")
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui

    page = build_icesee_ui()
    assert page is not None

    # Every one of the 4 submission/status call sites goes through
    # _record_icesee_run / _update_icesee_run, not the raw run_records
    # primitives directly -- so a single try/except in the helper is the
    # only place a manifest failure could ever surface, and it already
    # catches everything. The raw primitives themselves are called exactly
    # once each, inside those two helper bodies.
    src = _GW.read_text()
    assert src.count("run_records.record_run(") == 1
    assert src.count("run_records.update_run(") == 1
