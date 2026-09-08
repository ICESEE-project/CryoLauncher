
# ============================================================
#  Example registry (edit here to switch on/off, add or remove examples)
# ============================================================

# icesee_jupyter_book/core/example_registry.py
from __future__ import annotations

from pathlib import Path

from .paths import EXT


EXAMPLES = {
    "Lorenz-96 (fully runnable locally)": dict(
        enabled=True,
        base=EXT / "applications" / "lorenz_model" / "examples" / "lorenz96",
        run_script="run_da_lorenz96.py",
        params="params.yaml",
        report_nb="read_results.ipynb",
        assets=["_modelrun_datasets"],
        model_name="lorenz",
        figures_dir="figures",
        remote_rel="ICESEE/applications/lorenz_model/examples/lorenz96",
        remote_sbatch=None,
    ),
    "ISSM (fully runable in Remote)": dict(
        enabled=True,
        base=EXT / "applications" / "issm_model" / "examples" / "ISMIP_Choi",
        run_script="run_da_issm.py",
        params="params.yaml",
        report_nb="read_results.m",
        assets=["_modelrun_datasets"],
        model_name="issm",
        figures_dir="figures",
        remote_rel="ICESEE/applications/issm_model/examples/ISMIP_Choi",
        remote_sbatch="run_job_spack.sbatch",
    ),
    "Flowline (under development)": dict(
        enabled=True,
        base=EXT / "applications" / "flowline_model" / "examples" / "flowline_1d",
        run_script="run_da_flowline.py",
        params="params.yaml",
        report_nb="read_results.ipynb",
        assets=["_modelrun_datasets"],
        model_name="flowline",
        figures_dir="figures",
        remote_rel="ICESEE/applications/flowline_model/examples/flowline_1d",
        remote_sbatch=None,
    ),
    "Icepack (under development)": dict(
        enabled=True,
        base=EXT / "applications" / "icepack_model" / "examples" / "synthetic_ice_stream",
        run_script="run_da_icepack.py",
        params="params.yaml",
        report_nb="read_results.ipynb",
        assets=["_modelrun_datasets"],
        model_name="icepack",
        figures_dir="figures",
        remote_rel="ICESEE/applications/icepack_model/examples/synthetic_ice_stream",
        remote_sbatch=None,
    ),
}


def enabled_names() -> list[str]:
    return [k for k, v in EXAMPLES.items() if v.get("enabled", False)]


def get_example(name: str) -> dict:
    if name not in EXAMPLES:
        raise KeyError(f"Unknown example: {name}")
    return EXAMPLES[name]