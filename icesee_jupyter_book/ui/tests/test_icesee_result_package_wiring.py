"""ICESEE ResultPackage foundation + Results UI (Phases 3-4): selecting a
historical run in the Workspace shell reuses the existing figures/H5
preview AND adds a DA-aware summary (forecast/ensemble/observations,
categorised from ICESEE's own dataset names) built from
icesee_jupyter_book.core.results_package -- never a fabricated schema, and
never replacing the existing preview.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

h5py = pytest.importorskip("h5py")

_GW = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"


def test_gateway_imports_and_uses_the_result_package():
    src = _GW.read_text()
    assert (
        "from icesee_jupyter_book.core.results_package import discover_result_package"
        in src
    )
    assert "discover_result_package(run.workspace_directory)" in src
    assert "pkg.summary_lines()" in src
    # the existing ad-hoc preview is preserved, not replaced
    assert "refresh_results_preview(run.workspace_directory, results_out)" in src


def test_selecting_a_run_with_da_outputs_prints_a_categorized_summary(monkeypatch, tmp_path, capsys):
    import numpy as np

    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "result-package-wiring-user")
    monkeypatch.setenv("USER", "result-package-wiring-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    import matplotlib
    matplotlib.use("Agg")

    from cryostack_src.workspace import user_run_root
    from icesee_jupyter_book.core import run_records as rr

    root = user_run_root(app="icesee")
    run_dir = root / "da-summary-check"
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    with h5py.File(run_dir / "results" / "true-wrong-lorenz.h5", "w") as f:
        f.create_dataset("true_state", data=np.zeros((3, 5)))
        f.create_dataset("hu_obs", data=np.zeros((3, 2)))
    rr.record_run(
        run_dir=run_dir, run_id="da-summary-check", name="da summary check",
        params={}, example="lorenz96", execution_mode="local",
        backend="local", status="done",
    )

    import ipywidgets as W
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui

    page = build_icesee_ui()

    def freevar(fn, name):
        idx = fn.__code__.co_freevars.index(name)
        return fn.__closure__[idx].cell_contents

    found = {}

    def walk(w):
        notifiers = getattr(w, "_trait_notifiers", None)
        if notifiers and "value" in notifiers and "on_run_selected" not in found:
            for handlers in notifiers["value"].values():
                for h in handlers:
                    if getattr(h, "__name__", "") == "show_selection":
                        found["show_selection"] = (w, h)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    assert "show_selection" in found, "Runs selector (show_selection) not found"
    runs_select, show_selection = found["show_selection"]

    on_run_selected = freevar(show_selection, "on_run_selected")
    assert callable(on_run_selected)   # this IS _on_icesee_run_selected

    capsys.readouterr()   # drop build-time output
    runs_select.value = "da-summary-check"   # triggers show_selection -> on_run_selected
    printed = capsys.readouterr().out

    assert "DA outputs" in printed
    assert "Forecast/truth: true_state" in printed
    assert "Observations: hu_obs" in printed
