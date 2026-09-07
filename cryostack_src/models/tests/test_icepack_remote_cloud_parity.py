"""Icepack Remote <-> Cloud parity.

After the parity work, BOTH providers run the identical Icepack execution
contract:

    stage cryostack_icepack_{runner,export,postprocess}.py
      -> nbconvert a raw .ipynb target
      -> cryostack_icepack_runner.py <script> <run_dir>
           (headless Agg, run ONCE, figure capture + metadata, structured
            export -- exit code = the science's own)
      -> cryostack_icepack_postprocess.py  (stdlib collector, honest status)

Only the provider WRAPPER differs (AWS Batch `bash -c` vs. an sbatch
`apptainer exec` / `source activate.sh`). This suite proves the shared
pipeline is byte-identical and that its RESULT behaviour is the same for the
six representative run shapes -- with local/fake execution only, no AWS, no
HPC.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

from cryostack_src.cloud.runtime import (
    ICEPACK_EXPORT_FILENAME,
    ICEPACK_POSTPROCESS_FILENAME,
    ICEPACK_RUNNER_FILENAME,
    build_cloud_runner,
    icepack_postprocess_extra_files,
)
from cryostack_src.models.icepack import discover_results
from cryostack_src.models.icepack._export_core import export as _structured_export
from cryostack_src.models.icepack.export import (
    build_export_shell_block,
    export_module_source,
    runner_module_source,
)
from cryostack_src.models.icepack.postprocess import build_postprocess

pytest.importorskip("matplotlib")


# ── 1. the two providers stage + invoke the SAME contract ────────────────
def test_cloud_and_remote_stage_byte_identical_helpers():
    cloud = icepack_postprocess_extra_files()
    assert cloud[ICEPACK_RUNNER_FILENAME] == runner_module_source()
    assert cloud[ICEPACK_EXPORT_FILENAME] == export_module_source()
    assert cloud[ICEPACK_POSTPROCESS_FILENAME] == build_postprocess()

    remote = build_export_shell_block(
        run_dir="/run", example_dir="/ex", backend="container",
        sif_path="/i.sif", stack_binds="", run_file_name="run.py", primary=True)
    assert runner_module_source() in remote
    assert export_module_source() in remote


def test_both_invoke_the_runner_with_script_and_run_dir():
    cloud_runner = build_cloud_runner()
    assert f'"${{WORKDIR}}/{ICEPACK_RUNNER_FILENAME}"' in cloud_runner
    assert '"${SCRIPT}" "${WORKDIR}"' in cloud_runner

    remote = build_export_shell_block(
        run_dir="/run", example_dir="/ex", backend="spack", spack_path="/sp",
        run_file_name="run.py", primary=True)
    assert f'python "/run/{ICEPACK_RUNNER_FILENAME}" "/ex/run.py" "/run"' in remote


def test_remote_primary_run_propagates_science_exit_code():
    """primary=True: no `|| echo ... (non-fatal)` tail -- a failed science
    run fails the sbatch, exactly like the Cloud runner's `rc=$?`."""
    primary = build_export_shell_block(
        run_dir="/run", example_dir="/ex", backend="spack", spack_path="/sp",
        run_file_name="run.py", primary=True)
    assert "(non-fatal)" not in primary

    legacy = build_export_shell_block(
        run_dir="/run", example_dir="/ex", backend="spack", spack_path="/sp",
        run_file_name="run.py", primary=False)
    assert "(non-fatal)" in legacy


def test_remote_primary_nbconverts_a_raw_notebook_target():
    blk = build_export_shell_block(
        run_dir="/run", example_dir="/ex", backend="container", sif_path="/i.sif",
        run_file_name="00-x.ipynb", run_file_py="00-x.py", primary=True)
    assert 'jupyter nbconvert --to script "/ex/00-x.ipynb"' in blk
    assert 'python "/run/cryostack_icepack_runner.py" "/ex/00-x.py" "/run"' in blk


# ── 2. the shared pipeline: 6 representative run shapes ──────────────────
def _fake_firedrake(monkeypatch):
    """A minimal duck-typed firedrake so _export_core can run offline."""
    import numpy as np

    class _Dat:
        def __init__(self, a): self.data_ro = np.asarray(a)

    class _Fn:
        def __init__(self, v, sp, mesh=None):
            self._v = np.asarray(v, dtype=float); self._sp = sp; self._mesh = mesh
            self.dat = _Dat(self._v)
        def function_space(self): return self._sp
        def __getitem__(self, i): return _Fn(self._v[:, i], self._sp, self._mesh)
        def interpolate(self, o):
            self._v = np.asarray(getattr(o, "_v", o), dtype=float)
            self.dat = _Dat(self._v); return self

    class _El:
        def family(self): return "Lagrange"
        def degree(self): return 1

    class _Sp:
        def __init__(self, mesh): self._mesh = mesh
        def mesh(self): return self._mesh
        def ufl_element(self): return _El()

    class _CNM:
        def __init__(self, c): self.values = np.asarray(c)

    class _Coords:
        def __init__(self, xy, c):
            self.dat = _Dat(np.asarray(xy, dtype=float)); self._c = _CNM(c)
        def function_space(self):
            return types.SimpleNamespace(cell_node_map=lambda: self._c)

    class _Mesh:
        def __init__(self, xy, c): self.coordinates = _Coords(xy, c)

    fk = types.ModuleType("firedrake")
    fk.FunctionSpace = lambda mesh, fam, deg: _Sp(mesh)
    fk.Function = lambda sp: _Fn(np.zeros(sp._mesh.coordinates.dat.data_ro.shape[0]), sp,
                                 getattr(sp, "_mesh", None))
    monkeypatch.setitem(sys.modules, "firedrake", fk)
    return _Mesh, _Sp, _Fn


def _run_pipeline(run: Path, *, script_text: str, namespace=None):
    """Stage + run the shared runner (as a subprocess -- real matplotlib) and
    then the stdlib collector. Returns the IcepackResultPackage the Results
    tab would read. ``namespace`` (a dict) short-circuits the structured
    export step so tier-1 fields can be exercised without a real Firedrake."""
    (run / "cryostack_icepack_runner.py").write_text(runner_module_source())
    (run / "cryostack_icepack_export.py").write_text(export_module_source())
    script = run / "run.py"
    script.write_text(script_text)

    env = dict(os.environ); env.pop("MPLBACKEND", None)
    r = subprocess.run([sys.executable, str(run / "cryostack_icepack_runner.py"),
                        str(script), str(run)],
                       capture_output=True, text=True, env=env, cwd=str(run))
    if namespace is not None:
        # emulate a successful structured export having recognised fields
        _structured_export(namespace, str(run))

    coll = run / "cryostack_icepack_postprocess.py"
    coll.write_text(build_postprocess())
    p = subprocess.run([sys.executable, str(coll)], capture_output=True, text=True,
                       env={"CRYOSTACK_RUN_DIR": str(run), "CRYOSTACK_EXAMPLE_DIR": str(run),
                            "CRYOSTACK_RUN_STARTED": str(time.time() - 3600),
                            "PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    assert p.returncode == 0, p.stderr
    return r, discover_results(run)


def test_case_1_figures_only(tmp_path):
    run = tmp_path / "r"; run.mkdir()
    r, pkg = _run_pipeline(run, script_text=(
        "import matplotlib.pyplot as plt\n"
        "f, a = plt.subplots(); a.plot([0,1],[1,0]); a.set_title('Mesh')\n"
        "g, b = plt.subplots(); b.plot([0,1],[0,1])\n"))
    assert r.returncode == 0
    assert pkg.status == "artifacts"
    assert pkg.is_readable() is False
    assert pkg.available_solutions() == []
    caps = pkg.figure_captions()
    assert caps["figure-01.png"]["title"] == "Mesh"
    assert "title" not in caps.get("figure-02.png", {})


def test_case_2_recognized_structured_fields(tmp_path, monkeypatch):
    _Mesh, _Sp, _Fn = _fake_firedrake(monkeypatch)
    pytest.importorskip("h5py")
    run = tmp_path / "r"; run.mkdir()
    mesh = _Mesh([[0, 0], [1, 0], [0, 1], [1, 1]], [[0, 1, 2], [1, 3, 2]])
    sp = _Sp(mesh)
    ns = {"h": _Fn([10.0, 11, 12, 13], sp, mesh),
          "u": _Fn([[1.0, 0], [2, 0], [3, 1], [4, 1]], sp, mesh)}
    r, pkg = _run_pipeline(run, script_text="print('science ok')\n", namespace=ns)
    assert pkg.status == "ok"
    assert pkg.is_readable() is True
    assert set(pkg.available_fields()) == {"thickness", "velocity"}


def test_case_3_explicit_native_output(tmp_path):
    run = tmp_path / "r"; run.mkdir()
    r, pkg = _run_pipeline(run, script_text=(
        "open('checkpoint.h5','wb').write(b'\\x89HDF\\r\\n')\n"))
    assert pkg.status == "artifacts"
    assert pkg.is_readable() is False
    assert "checkpoint.h5" in [Path(f).name for f in pkg.legacy_artifacts()["native"]]


def test_case_4_mixed_figures_and_fields(tmp_path, monkeypatch):
    _Mesh, _Sp, _Fn = _fake_firedrake(monkeypatch)
    pytest.importorskip("h5py")
    run = tmp_path / "r"; run.mkdir()
    mesh = _Mesh([[0, 0], [1, 0], [0, 1], [1, 1]], [[0, 1, 2], [1, 3, 2]])
    sp = _Sp(mesh)
    ns = {"h": _Fn([1.0, 2, 3, 4], sp, mesh)}
    r, pkg = _run_pipeline(run, namespace=ns, script_text=(
        "import matplotlib.pyplot as plt\n"
        "f, a = plt.subplots(); a.plot([0,1],[1,0]); a.set_title('Thickness field')\n"))
    assert pkg.status == "ok"                      # fields win the status
    assert pkg.is_readable() is True
    assert "thickness" in pkg.available_fields()
    # the figure + its metadata still ride along
    assert any("figure-01.png" in str(p) for p in pkg.figures())
    assert pkg.figure_captions()["figure-01.png"]["title"] == "Thickness field"


def test_case_5_empty_result(tmp_path):
    run = tmp_path / "r"; run.mkdir()
    r, pkg = _run_pipeline(run, script_text="x = 2 + 2\nprint(x)\n")
    assert r.returncode == 0
    # in the real tested image (Firedrake present) this is "empty"; without
    # Firedrake the exporter honestly records "export_failed" -- either way
    # the CONTRACT is the same: nothing renderable, no fabricated fields.
    assert pkg.status in ("empty", "export_failed")
    assert pkg.is_readable() is False
    assert pkg.available_solutions() == []
    assert pkg.figures() == []


def test_case_6_failed_science_execution(tmp_path):
    run = tmp_path / "r"; run.mkdir()
    r, pkg = _run_pipeline(run, script_text=(
        "import matplotlib.pyplot as plt\n"
        "f, a = plt.subplots(); a.plot([0,1],[1,0])\n"
        "raise RuntimeError('solver diverged')\n"))
    assert r.returncode != 0                       # the science failure propagates
    assert "solver diverged" in (r.stderr + r.stdout)
    # the collector still writes an honest package for whatever landed
    assert pkg.status in ("artifacts", "empty")
