"""Dedicated coverage for the Icepack model adapter (parity area 15 -- there
were previously zero Icepack-adapter tests). Scientific-difference behaviours
are asserted as such, not forced to match ISSM.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cryostack_src.models import get_model_adapter
from cryostack_src.models import icepack


# ── adapter registration / surface ────────────────────────────────────
def test_adapter_is_registered_and_exposes_the_shared_surface():
    adapter = get_model_adapter("ICEPACK")          # case-insensitive
    assert adapter is icepack
    for fn in ("build_run_command", "build_slurm_script", "build_postprocess",
               "validate_configuration", "build_environment_check",
               "build_activation_check", "build_container_fragment",
               "choose_run_target", "order_run_targets", "example_runnable",
               "example_template", "discover_results"):
        assert callable(getattr(adapter, fn)), fn


def test_unknown_model_still_rejected():
    with pytest.raises(ValueError):
        get_model_adapter("firedrake")


# ── example discovery: notebooks/scripts, not runme.m ─────────────────
def test_example_runnable_accepts_notebook_or_script_dirs(tmp_path):
    nb = tmp_path / "tutorial"; nb.mkdir()
    (nb / "ice-shelf.ipynb").write_text("{}")
    assert icepack.example_runnable(nb) is True

    scr = tmp_path / "howto"; scr.mkdir()
    (scr / "run.py").write_text("import icepack\n")
    assert icepack.example_runnable(scr) is True

    empty = tmp_path / "empty"; empty.mkdir()
    assert icepack.example_runnable(empty) is False


def test_example_entrypoints_is_open_ended_unlike_issm():
    assert icepack.EXAMPLE_ENTRYPOINTS == ()          # scientific difference
    assert icepack.example_template() is None


@pytest.mark.parametrize("names,expected", [
    (["ice-shelf.ipynb", "helpers.py", "mesh.geo"], "ice-shelf.ipynb"),
    (["run.py", "data.h5"], "run.py"),
    (["a.m", "b.py"], "b.py"),                        # .py beats a stray .m
    (["only.geo"], "only.geo"),
    ([], ""),
    # Icepack Cloud Execution checkpoint: a materialized notebook working
    # copy stages BOTH the original notebook and the generated run.py --
    # run.py (never hand-maintained, always this exact name) wins even
    # though a bare .ipynb would otherwise be preferred.
    (["00-meshes-functions.ipynb", "run.py"], "run.py"),
    (["run.py", "00-meshes-functions.ipynb", ".cryostack-example.json"], "run.py"),
])
def test_choose_run_target_prefers_python(names, expected):
    assert icepack.choose_run_target(names) == expected


def test_order_run_targets_puts_run_py_first_even_over_a_notebook():
    ordered = icepack.order_run_targets(["00-meshes-functions.ipynb", "run.py", "mesh.geo"])
    assert ordered[0] == "run.py"


# ── run-command shapes (spack + apptainer) ───────────────────────────
@pytest.mark.parametrize("backend,target,must_contain,must_not", [
    # an Icepack run goes through the shared runner (headless + figure
    # capture + structured export), never a bare `python <script>`
    ("spack", "sim.py", 'cryostack_icepack_runner.py" "sim.py"', "apptainer"),
    ("spack", "nb.ipynb", "nbconvert --to script", "matlab"),
    ("spack", "", 'import icepack', "matlab"),
    ("container", "sim.py", 'with-icepack bash -lc', "with-issm"),
    ("container", "sim.py", 'cryostack_icepack_runner.py" "sim.py"', "with-issm"),
    ("container", "nb.ipynb", "with-icepack bash -lc", "matlab"),
])
def test_build_run_command(backend, target, must_contain, must_not):
    cmd = icepack.build_run_command(
        backend=backend, target=target, example_dir="/ex", exec_dir="/exec",
        image_uri="/img.sif", ntasks=4)
    assert must_contain in cmd
    assert must_not not in cmd
    assert "matlab" not in cmd.lower()               # never MATLAB
    # never a bare double execution
    assert cmd.count("python ") <= 2                  # nbconvert + runner at most


def test_activation_check_is_a_python_import():
    chk = icepack.build_activation_check()
    assert "import icepack" in chk
    assert "issmversion" not in chk


def test_environment_check_probes_icepack_and_firedrake_for_spack():
    chk = icepack.build_environment_check(
        spack_path="/spack", sif_path="/x.sif", backend="spack")
    assert "import icepack" in chk and "import firedrake" in chk
    # container path delegates to the shared container check, no firedrake probe
    c = icepack.build_environment_check(
        spack_path="/spack", sif_path="/x.sif", backend="container")
    assert "firedrake" not in c


def test_validate_configuration_is_passthrough_for_now():
    assert icepack.validate_configuration({"a": 1}) == {"a": 1}
    assert icepack.validate_configuration(None) == {}


def test_container_fragment_uses_with_icepack():
    frag = icepack.build_container_fragment(
        example_dir="/ex", sif_path="/x.sif", target="sim.py")
    assert "with-icepack" in frag and "with-issm" not in frag


# ── it must NOT pretend to have ISSM's md-config surface ──────────────
def test_icepack_has_no_md_config_api():
    for absent in ("CURATED_MD_PARAMETERS", "build_md_override_script",
                   "detect_solvers", "validate_md_config"):
        assert not hasattr(icepack, absent), absent
