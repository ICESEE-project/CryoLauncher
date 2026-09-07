"""ICESEE persisted run identity + history (`core/run_records.py`).

ICESEE now records each run as a `.cryostack-run.json` manifest -- the same
model-neutral primitive CryoLauncher uses -- while keeping the full
data-assimilation identity (filter, ensemble, observations, state/parameter
estimation, DA cycle) in the manifest metadata.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.core import run_records as rr

_LORENZ_PARAMS = {
    "physical-parameters": {"sigma_96": 10.0},
    "modeling-parameters": {
        "dt": 0.01, "num_years": 10, "timesteps_per_year": 2,
        "example_name": "lorenz96",
    },
    "enkf-parameters": {
        "Nens": 30, "freq_obs": 0.2, "obs_max_time": 2, "obs_start_time": 0.1,
        "num_state_vars": 3, "num_param_vars": 0,
        "vec_inputs": ["x", "y", "z"], "observed_vars": ["x", "y", "z"],
        "sig_obs": [0.1, 0.1, 0.1],
        "joint_estimation": False, "state_estimation": True,
        "parameter_estimation": False,
        "seed": 1, "inflation_factor": 1.0, "localization_flag": 0,
        "model_name": "lorenz", "filter_type": "EnKF",
        "parallel_flag": "serial", "execution_mode": 0,
    },
}


def test_da_identity_extracts_the_full_workflow():
    ident = rr.da_identity_from_params(_LORENZ_PARAMS)
    assert ident.forecast_model == "lorenz"
    assert ident.example_name == "lorenz96"
    assert ident.assimilation_filter == "EnKF"
    assert ident.ensemble_size == 30
    assert ident.parallel_flag == "serial"
    assert ident.execution_flag == 0
    assert ident.obs_frequency == 0.2
    assert ident.obs_start_time == 0.1
    assert ident.obs_max_time == 2
    assert ident.observed_vars == ["x", "y", "z"]
    assert ident.state_vars == ["x", "y", "z"]
    assert ident.num_state_vars == 3
    assert ident.state_estimation is True
    assert ident.parameter_estimation is False
    assert ident.dt == 0.01
    assert ident.num_years == 10


def test_da_identity_tolerates_a_sparse_params_dict():
    ident = rr.da_identity_from_params({"enkf-parameters": {"filter_type": "DEnKF"}})
    assert ident.assimilation_filter == "DEnKF"
    assert ident.ensemble_size is None
    assert ident.observed_vars == []
    # nothing crashes, and to_dict is JSON-safe
    assert isinstance(ident.to_dict()["observations"]["observed_vars"], list)


def test_da_identity_handles_string_estimation_flags():
    ident = rr.da_identity_from_params(
        {"enkf-parameters": {"parameter_estimation": "true", "state_estimation": "False"}}
    )
    assert ident.parameter_estimation is True
    assert ident.state_estimation is False


def test_summary_rows_omit_empty_values():
    ident = rr.da_identity_from_params(_LORENZ_PARAMS)
    rows = dict(ident.summary_rows())
    assert rows["Assimilation filter"] == "EnKF"
    assert rows["Ensemble size"] == "30"
    assert rows["Estimating"] == "state"
    # a key ICESEE example never sets must not appear as an empty row
    sparse = rr.da_identity_from_params({"enkf-parameters": {"filter_type": "EnKF"}})
    labels = [label for label, _ in sparse.summary_rows()]
    assert "Ensemble size" not in labels
    assert "Observation window" not in labels


def test_build_run_metadata_carries_provider_and_da_identity_no_secrets():
    meta = rr.build_run_metadata(
        params=_LORENZ_PARAMS,
        example="Lorenz-96 (fully runnable in GHUB)",
        execution_mode="Local",
        backend="",
        source="EnKF_all_types.ipynb",
        run_target="run_da_lorenz96.py",
        model_environment="ICESEE (external checkout)",
    )
    assert meta["execution_mode"] == "local"
    assert meta["source"] == "EnKF_all_types.ipynb"
    assert meta["run_target"] == "run_da_lorenz96.py"
    assert meta["da"]["assimilation_filter"] == "EnKF"
    assert meta["da"]["state"]["state_estimation"] is True
    assert meta["forecast_model"] == "lorenz"
    assert meta["assimilation_filter"] == "EnKF"
    assert meta["ensemble_size"] == 30
    blob = repr(meta).lower()
    for banned in ("password", "secret", "token", "aws_access", "externalid"):
        assert banned not in blob


def test_record_and_discover_round_trip(tmp_path):
    run_dir = tmp_path / "20260907_120000-abc123"
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "figures").mkdir(parents=True)

    info = rr.record_run(
        run_dir=run_dir,
        run_id="20260907_120000-abc123",
        name="ICESEE EnKF run",
        params=_LORENZ_PARAMS,
        example="Lorenz-96 (fully runnable in GHUB)",
        execution_mode="local",
        backend="",
        source="EnKF_all_types.ipynb",
        run_target="run_da_lorenz96.py",
    )
    assert info.model == "icesee"
    assert (run_dir / ".cryostack-run.json").is_file()

    runs = rr.discover_runs(root=tmp_path)
    assert len(runs) == 1
    got = runs[0]
    assert got.id == "20260907_120000-abc123"
    assert got.execution_mode == "local"
    assert got.metadata["da"]["assimilation_filter"] == "EnKF"
    assert got.metadata["da"]["observations"]["observed_vars"] == ["x", "y", "z"]
    assert got.metadata["run_target"] == "run_da_lorenz96.py"
    assert got.results_directory is not None


def test_update_run_sets_status_and_finished(tmp_path):
    run_dir = tmp_path / "r1"
    run_dir.mkdir()
    rr.record_run(
        run_dir=run_dir, run_id="r1", name="x", params=_LORENZ_PARAMS,
        example="e", execution_mode="remote", backend="spack",
    )
    updated = rr.update_run(run_dir, status="done", jobid="12345")
    assert updated is not None
    assert updated.status == "done"
    assert updated.finished is not None
    assert updated.jobid == "12345"

    reread = rr.load_run(tmp_path, "r1")
    assert reread.status == "done"
    assert reread.jobid == "12345"


def test_update_run_without_a_manifest_is_a_noop(tmp_path):
    assert rr.update_run(tmp_path / "nope") is None


def test_discover_runs_newest_first_and_skips_bad_manifests(tmp_path):
    for name in ("r1", "r2"):
        d = tmp_path / name
        d.mkdir()
        rr.record_run(
            run_dir=d, run_id=name, name=name, params=_LORENZ_PARAMS,
            example="e", execution_mode="local", backend="",
        )
        time.sleep(0.01)
    bad = tmp_path / "r3"
    bad.mkdir()
    (bad / ".cryostack-run.json").write_text("{ not json")

    runs = rr.discover_runs(root=tmp_path)
    assert [r.id for r in runs] == ["r2", "r1"]


def test_da_filters_constant_matches_the_gateway_dropdown():
    assert rr.KNOWN_FILTERS == ("EnKF", "DEnKF", "EnTKF", "EnRSKF")
