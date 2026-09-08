"""IceseeResultPackage (Phase 3): the smallest viable DA-aware schema over
outputs ICESEE already writes -- HDF5 datasets under results/ and PNGs
under figures/. Categorisation matches the dataset names ICESEE's own EnKF
pipeline actually writes (external/ICESEE/src/EnKF/*.py):
true_state/nurged_state (forecast/truth), ensemble/ensemble_mean
(ensemble), hu_obs/R (observations).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

h5py = pytest.importorskip("h5py")
import numpy as np

from icesee_jupyter_book.core.results_package import (
    discover_result_package,
    inspect_h5_file,
)


def _write_h5(path: Path, datasets: dict):
    with h5py.File(path, "w") as f:
        for name, array in datasets.items():
            f.create_dataset(name, data=array)


def test_inspect_h5_file_categorizes_real_icesee_dataset_names(tmp_path):
    h5_path = tmp_path / "true-wrong-lorenz.h5"
    _write_h5(h5_path, {
        "true_state": np.zeros((3, 10)),
        "nurged_state": np.zeros((3, 10)),
        "ensemble": np.zeros((3, 20, 10)),
        "ensemble_mean": np.zeros((3, 10)),
        "hu_obs": np.zeros((3, 5)),
        "R": np.eye(3),
        "some_other_diagnostic": np.zeros((4,)),
    })

    artifact = inspect_h5_file(h5_path)
    by_name = {d.name: d for d in artifact.datasets}

    assert by_name["true_state"].category == "forecast"
    assert by_name["nurged_state"].category == "forecast"
    assert by_name["ensemble"].category == "ensemble"
    assert by_name["ensemble_mean"].category == "ensemble"
    assert by_name["hu_obs"].category == "observations"
    assert by_name["R"].category == "observations"
    assert by_name["some_other_diagnostic"].category == "model_native"
    assert by_name["ensemble"].shape == (3, 20, 10)


def test_discover_result_package_reads_only_whats_actually_there(tmp_path):
    run_dir = tmp_path / "run-a"
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "figures").mkdir()
    _write_h5(run_dir / "results" / "true-wrong-lorenz.h5", {
        "true_state": np.zeros((3, 5)),
        "hu_obs": np.zeros((3, 2)),
    })
    (run_dir / "figures" / "state.png").write_bytes(b"\x89PNG\r\n")

    pkg = discover_result_package(run_dir)
    assert not pkg.is_empty()
    assert len(pkg.h5_artifacts) == 1
    assert len(pkg.figures) == 1
    assert [d.name for d in pkg.forecast()] == ["true_state"]
    assert [d.name for d in pkg.observations()] == ["hu_obs"]
    assert pkg.ensemble() == ()


def test_discover_result_package_is_honest_about_an_empty_run(tmp_path):
    run_dir = tmp_path / "empty-run"
    run_dir.mkdir()
    pkg = discover_result_package(run_dir)
    assert pkg.is_empty()
    assert pkg.h5_artifacts == ()
    assert pkg.figures == ()
    assert pkg.summary_lines() == []


def test_summary_lines_report_category_shape_and_dtype(tmp_path):
    run_dir = tmp_path / "run-b"
    (run_dir / "results").mkdir(parents=True)
    _write_h5(run_dir / "results" / "state.h5", {
        "ensemble_mean": np.zeros((3, 7), dtype="f8"),
    })
    pkg = discover_result_package(run_dir)
    lines = pkg.summary_lines()
    assert len(lines) == 1
    assert "Ensemble: ensemble_mean" in lines[0]
    assert "[3, 7]" in lines[0]
    assert "float64" in lines[0]


def test_a_corrupt_h5_file_is_skipped_not_fatal(tmp_path):
    run_dir = tmp_path / "run-c"
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "results" / "corrupt.h5").write_bytes(b"not an hdf5 file")
    pkg = discover_result_package(run_dir)
    assert pkg.h5_artifacts == ()   # skipped, discovery itself did not raise
