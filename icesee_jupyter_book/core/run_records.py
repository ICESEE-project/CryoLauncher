"""Persisted run identity + history for ICESEE, on the shared CryoStack
manifest primitives.

CryoLauncher (IceSheets) records every run as a ``.cryostack-run.json``
manifest in a per-user workspace directory and rebuilds its Runs / Files /
Run Log / Results panels from those manifests. ICESEE historically kept no
local record -- it only POSTed an experiment row to the web API through the
browser bridge -- so a finished ICESEE run could not be re-selected, its
configuration could not be recovered, and its outputs were found only by an
ad-hoc ``rglob``.

This module gives ICESEE the same persisted-run model **without flattening the
data-assimilation workflow into a generic single-model run**. It reuses the
model-neutral :class:`~cryostack_src.workspace.RunInfo` +
:func:`~cryostack_src.workspace.write_manifest` /
:func:`~cryostack_src.workspace.read_manifest`, and stores the DA identity
(forecast model, assimilation filter, ensemble size, observation window, state
variables, estimated parameters, DA cycle configuration, execution
mode/backend, source / run target, outputs / provenance) in the manifest's
free-form ``metadata`` block.

Nothing here talks to AWS, HPC, or the web API; it is pure local filesystem
state scoped to the authenticated CryoStack user.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cryostack_src.workspace import (
    RunInfo,
    read_manifest,
    resolve_workspace_user,
    user_run_root,
    write_manifest,
)
from cryostack_src.workspace.manifest import MANIFEST_NAME

APP = "icesee"
MODEL = "icesee"

#: the DA filters ICESEE ships (params ``enkf-parameters.filter_type``)
KNOWN_FILTERS = ("EnKF", "DEnKF", "EnTKF", "EnRSKF")


# ─────────────────────────────────────────────────────────────────────────────
# DA identity
# ─────────────────────────────────────────────────────────────────────────────
def _section(params: dict, name: str) -> dict:
    value = (params or {}).get(name)
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


@dataclass(frozen=True)
class DAIdentity:
    """The data-assimilation identity of one ICESEE run, derived from its
    ``params.yaml`` (the nested ``physical- / modeling- / enkf-parameters``
    dict the gateway builds). Every field is JSON-safe."""

    forecast_model: str = ""
    example_name: str = ""
    assimilation_filter: str = ""
    ensemble_size: int | None = None
    parallel_flag: str = ""
    execution_flag: int | None = None

    # observations
    obs_frequency: float | None = None
    obs_start_time: float | None = None
    obs_max_time: float | None = None
    observed_vars: list = field(default_factory=list)
    obs_sigma: list = field(default_factory=list)

    # state / parameters
    state_vars: list = field(default_factory=list)
    num_state_vars: int | None = None
    num_param_vars: int | None = None
    joint_estimation: bool | None = None
    state_estimation: bool | None = None
    parameter_estimation: bool | None = None

    # DA cycle
    dt: float | None = None
    num_years: float | None = None
    timesteps_per_year: float | None = None
    seed: Any = None
    inflation_factor: float | None = None
    localization: Any = None

    def to_dict(self) -> dict:
        return {
            "forecast_model": self.forecast_model,
            "example_name": self.example_name,
            "assimilation_filter": self.assimilation_filter,
            "ensemble_size": self.ensemble_size,
            "parallel_flag": self.parallel_flag,
            "execution_flag": self.execution_flag,
            "observations": {
                "frequency": self.obs_frequency,
                "start_time": self.obs_start_time,
                "max_time": self.obs_max_time,
                "observed_vars": list(self.observed_vars),
                "sigma": list(self.obs_sigma),
            },
            "state": {
                "variables": list(self.state_vars),
                "num_state_vars": self.num_state_vars,
                "num_param_vars": self.num_param_vars,
                "joint_estimation": self.joint_estimation,
                "state_estimation": self.state_estimation,
                "parameter_estimation": self.parameter_estimation,
            },
            "da_cycle": {
                "dt": self.dt,
                "num_years": self.num_years,
                "timesteps_per_year": self.timesteps_per_year,
                "seed": self.seed,
                "inflation_factor": self.inflation_factor,
                "localization": self.localization,
            },
        }

    def summary_rows(self) -> list[tuple[str, str]]:
        """(label, value) pairs for a Run Plan / history card. Only non-empty
        rows -- an ICESEE example that does not set a key is simply omitted."""
        est = []
        if self.state_estimation:
            est.append("state")
        if self.parameter_estimation:
            est.append("parameters")
        if self.joint_estimation:
            est.append("joint")
        obs_window = ""
        if self.obs_start_time is not None or self.obs_max_time is not None:
            obs_window = f"{self.obs_start_time if self.obs_start_time is not None else '?'}"
            obs_window += f" – {self.obs_max_time if self.obs_max_time is not None else '?'}"
            if self.obs_frequency is not None:
                obs_window += f" (every {self.obs_frequency})"
        rows = [
            ("Forecast model", self.forecast_model or self.example_name),
            ("Assimilation filter", self.assimilation_filter),
            ("Ensemble size", str(self.ensemble_size) if self.ensemble_size else ""),
            ("Observed variables", ", ".join(str(v) for v in self.observed_vars)),
            ("Observation window", obs_window),
            ("State variables", ", ".join(str(v) for v in self.state_vars)),
            ("Estimating", ", ".join(est)),
            ("Parallel mode", self.parallel_flag),
        ]
        return [(label, value) for label, value in rows if value]


def da_identity_from_params(params: dict) -> DAIdentity:
    """Extract the DA identity from a nested ICESEE params dict. Missing keys
    are tolerated -- an ICESEE example only fills what it needs."""
    modeling = _section(params, "modeling-parameters")
    enkf = _section(params, "enkf-parameters")

    def _num(section: dict, key: str):
        value = section.get(key)
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return value
        try:
            return float(value) if "." in str(value) else int(value)
        except (TypeError, ValueError):
            return None

    def _flag(section: dict, key: str):
        value = section.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes")
        return None

    ens = enkf.get("Nens")
    try:
        ens = int(ens) if ens is not None else None
    except (TypeError, ValueError):
        ens = None

    exec_flag = enkf.get("execution_mode")
    try:
        exec_flag = int(exec_flag) if exec_flag is not None else None
    except (TypeError, ValueError):
        exec_flag = None

    return DAIdentity(
        forecast_model=str(enkf.get("model_name") or modeling.get("model_name") or ""),
        example_name=str(modeling.get("example_name") or ""),
        assimilation_filter=str(enkf.get("filter_type") or ""),
        ensemble_size=ens,
        parallel_flag=str(enkf.get("parallel_flag") or ""),
        execution_flag=exec_flag,
        obs_frequency=_num(enkf, "freq_obs"),
        obs_start_time=_num(enkf, "obs_start_time"),
        obs_max_time=_num(enkf, "obs_max_time"),
        observed_vars=_as_list(enkf.get("observed_vars")),
        obs_sigma=_as_list(enkf.get("sig_obs")),
        state_vars=_as_list(enkf.get("vec_inputs")),
        num_state_vars=_num(enkf, "num_state_vars"),
        num_param_vars=_num(enkf, "num_param_vars"),
        joint_estimation=_flag(enkf, "joint_estimation"),
        state_estimation=_flag(enkf, "state_estimation"),
        parameter_estimation=_flag(enkf, "parameter_estimation"),
        dt=_num(modeling, "dt"),
        num_years=_num(modeling, "num_years"),
        timesteps_per_year=_num(modeling, "timesteps_per_year"),
        seed=enkf.get("seed"),
        inflation_factor=_num(enkf, "inflation_factor"),
        localization=enkf.get("localization_flag"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# manifest metadata
# ─────────────────────────────────────────────────────────────────────────────
def build_run_metadata(
    *,
    params: dict,
    example: str,
    execution_mode: str,
    backend: str,
    source: str = "",
    run_target: str = "",
    model_environment: str = "",
    extra: dict | None = None,
) -> dict:
    """The manifest ``metadata`` block for an ICESEE run: the formal
    execution-provider concepts (execution mode / compute backend / model
    environment / source / run target) plus the full DA identity. No secrets."""
    identity = da_identity_from_params(params)
    meta = {
        "app": APP,
        "example": example,
        "execution_mode": (execution_mode or "").strip().lower(),
        "backend": (backend or "").strip().lower(),
        "model_environment": model_environment,
        "source": source,
        "run_target": run_target,
        "da": identity.to_dict(),
        # convenience top-level mirrors for cheap history-card rendering
        "forecast_model": identity.forecast_model or identity.example_name,
        "assimilation_filter": identity.assimilation_filter,
        "ensemble_size": identity.ensemble_size,
    }
    if extra:
        meta.update({k: v for k, v in extra.items() if k not in meta})
    return meta


# ─────────────────────────────────────────────────────────────────────────────
# run store
# ─────────────────────────────────────────────────────────────────────────────
def runs_root(*, require_authenticated: bool = False) -> Path:
    """The per-user, per-app ICESEE run root -- the same directory
    ``icesee_gateway._icesee_run_dir_base()`` already routes runs into."""
    return user_run_root(app=APP, require_authenticated=require_authenticated)


def record_run(
    *,
    run_dir: Path | str,
    run_id: str,
    name: str,
    params: dict,
    example: str,
    execution_mode: str,
    backend: str,
    source: str = "",
    run_target: str = "",
    model_environment: str = "",
    status: str = "submitted",
    jobid: str | None = None,
    remote_directory: Path | str | None = None,
    created: datetime | None = None,
    extra_metadata: dict | None = None,
) -> RunInfo:
    """Write a ``.cryostack-run.json`` manifest for an ICESEE run into
    ``run_dir`` and return the :class:`RunInfo`. Idempotent for a given
    ``run_dir`` -- a later call (e.g. status update) overwrites it."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    results_dir = run_dir / "results"
    figures_dir = run_dir / "figures"
    info = RunInfo(
        id=run_id,
        name=name,
        model=MODEL,
        backend=(backend or "").strip().lower(),
        execution_mode=(execution_mode or "").strip().lower(),
        status=status,
        created=created or datetime.now(),
        workspace_directory=run_dir.resolve(),
        remote_directory=Path(remote_directory) if remote_directory else None,
        results_directory=results_dir if results_dir.exists() else None,
        figures_directory=figures_dir if figures_dir.exists() else None,
        jobid=str(jobid) if jobid is not None else None,
        metadata=build_run_metadata(
            params=params,
            example=example,
            execution_mode=execution_mode,
            backend=backend,
            source=source,
            run_target=run_target,
            model_environment=model_environment,
            extra=extra_metadata,
        ),
    )
    write_manifest(info, run_dir.resolve())
    return info


def update_run(
    run_dir: Path | str,
    *,
    status: str | None = None,
    finished: datetime | None = None,
    jobid: str | None = None,
    remote_directory: Path | str | None = None,
    extra_metadata: dict | None = None,
) -> RunInfo | None:
    """Re-read a run's manifest, apply changes, and write it back. Returns the
    updated :class:`RunInfo`, or ``None`` if there is no manifest to update."""
    run_dir = Path(run_dir)
    manifest = run_dir / MANIFEST_NAME
    if not manifest.is_file():
        return None
    info = read_manifest(manifest)
    if status is not None:
        info.status = status
    if finished is not None:
        info.finished = finished
    elif status in ("done", "completed", "succeeded", "failed", "error") and info.finished is None:
        info.finished = datetime.now()
    if jobid is not None:
        info.jobid = str(jobid)
    if remote_directory is not None:
        info.remote_directory = Path(remote_directory)
    if extra_metadata:
        info.metadata = {**info.metadata, **extra_metadata}
    results_dir = run_dir / "results"
    figures_dir = run_dir / "figures"
    if info.results_directory is None and results_dir.exists():
        info.results_directory = results_dir
    if info.figures_directory is None and figures_dir.exists():
        info.figures_directory = figures_dir
    write_manifest(info, run_dir.resolve())
    return info


def discover_runs(root: Path | str | None = None) -> list[RunInfo]:
    """Every ICESEE run under ``root`` (default: the current user's run root),
    newest first. A malformed manifest is skipped, never fatal."""
    base = Path(root) if root is not None else runs_root()
    if not base.is_dir():
        return []
    found: list[RunInfo] = []
    for manifest in base.glob(f"*/{MANIFEST_NAME}"):
        try:
            found.append(read_manifest(manifest))
        except Exception:  # noqa: BLE001 - one bad manifest must not hide the rest
            continue
    found.sort(key=lambda r: r.created, reverse=True)
    return found


def load_run(root: Path | str | None, run_id: str) -> RunInfo | None:
    base = Path(root) if root is not None else runs_root()
    manifest = base / run_id / MANIFEST_NAME
    if not manifest.is_file():
        return None
    try:
        return read_manifest(manifest)
    except Exception:  # noqa: BLE001
        return None
