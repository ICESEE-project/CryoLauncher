"""Icepack remote submission renders the neutral output-collection step so a
successful Icepack run produces a structured outputs/ package (parity area 9-11).

The collection step must be non-fatal and stdlib-only; the ISSM MATLAB
neutral-export must never appear in an Icepack job.
"""
from __future__ import annotations

import base64
import re
import sys
import tempfile
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

import cryostack_src.models.submission as submission
from cryostack_src.resources.profiles import get_compute_profile


class _Result:
    def __init__(self, stdout="", rc=0):
        self.returncode, self.stdout, self.stderr = rc, stdout, ""


@pytest.fixture
def render_icepack(monkeypatch):
    def _fake_ssh_run(host, user, port, cmd, timeout=20):
        if "run_icesheets.sbatch" in cmd and "b64decode" in cmd:
            for blob in sorted(re.findall(r"[A-Za-z0-9+/]{80,}={0,2}", cmd),
                               key=len, reverse=True):
                try:
                    _fake_ssh_run.sbatch = base64.b64decode(blob).decode()
                    break
                except Exception:
                    continue
        if cmd.strip().startswith("sbatch"):
            return _Result("Submitted batch job 4242\n")
        if cmd.strip().startswith("test -f"):
            return _Result("FOUND\n")
        return _Result("/abs/ok\n")

    monkeypatch.setattr(submission, "ssh_run", _fake_ssh_run)
    monkeypatch.setattr(submission, "resolve_remote_abs_path", lambda *a, **k: "/home/u/base")
    monkeypatch.setattr(submission, "expand_remote_home", lambda x: x)
    monkeypatch.setattr(submission, "subprocess",
                        types.SimpleNamespace(run=lambda *a, **k: _Result()),
                        raising=False)

    example = Path(tempfile.mkdtemp()) / "ice-shelf"
    example.mkdir()
    (example / "ice-shelf.py").write_text("import icepack\n")

    def _render(*, backend="container", run_file="ice-shelf.py"):
        _fake_ssh_run.sbatch = ""
        submission.submit_remote_icesheets(
            host="login", user="u", port=22,
            remote_base_dir="~/base", remote_tag="icesheets",
            backend=backend, model="icepack",
            example_dir=str(example), exec_dir=str(example),
            image_uri="/shared/images/combined.sif", container_source="local",
            spack_enable=(backend == "spack"), spack_repo_url="",
            spack_dirname="ICESEE-Spack", spack_install_if_needed=False,
            spack_install_mode="--with-icepack", spack_slurm_dir="", spack_pmix_dir="",
            slurm_time="01:00:00", slurm_job_name="ICEPACK", slurm_nodes=1,
            slurm_ntasks=4, slurm_tpn=4, slurm_part="cpu", slurm_mem="16G",
            slurm_account="", slurm_mail="", test_mode=False, run_file=run_file,
            matlab_license=get_compute_profile("pace").matlab_license_config(),
        )
        return _fake_ssh_run.sbatch

    return _render


def test_icepack_job_collects_outputs_and_has_no_matlab(render_icepack):
    txt = render_icepack(backend="container")
    # the scientific run: ONE step, via the shared runner (same contract as
    # the Cloud path) inside with-icepack -- runs the science, captures
    # headless figures + metadata, then structured-exports.
    assert "with-icepack bash -lc" in txt
    assert "cryostack_icepack_runner.py" in txt and 'ice-shelf.py"' in txt
    assert "cryostack_icepack_export.py" in txt          # exporter staged
    # the science exit code is NOT swallowed (primary run, not the old
    # non-fatal appended re-run)
    assert "icepack structured export step failed (non-fatal)" not in txt
    # the science script is not ALSO run bare (no double execution)
    assert 'python "ice-shelf.py"\n' not in txt
    # the neutral collection step
    assert "CRYOSTACK_RUN_STARTED" in txt
    assert "cryostack_icepack_postprocess.py" in txt
    assert "Icepack output collection failed (the run itself completed)" in txt  # non-fatal
    assert "CRYOSTACK_ICEPACK_PP_EOF" in txt
    # NEVER the ISSM MATLAB export
    assert "with-issm matlab" not in txt
    assert "postprocess_icesee.m" not in txt
    assert "md.results" not in txt


def test_collection_step_is_stdlib_only_and_guarded(render_icepack):
    txt = render_icepack()
    # guarded on python3 availability, never hard-fails the job
    assert "command -v python3" in txt
    collector = txt.split("CRYOSTACK_ICEPACK_PP_EOF")[1]
    assert "import icepack" not in collector and "import firedrake" not in collector


def test_connector_icepack_submission_also_collects(monkeypatch, tmp_path):
    def _fake_connector_ssh(session_id, host, user, port, cmd, timeout=20, cluster_name="pace"):
        if "run_icesheets.sbatch" in cmd and "b64decode" in cmd:
            for blob in sorted(re.findall(r"[A-Za-z0-9+/]{80,}={0,2}", cmd),
                               key=len, reverse=True):
                try:
                    _fake_connector_ssh.sbatch = base64.b64decode(blob).decode()
                    break
                except Exception:
                    continue
        return {"ok": True, "stdout": "/home/u/base\n", "stderr": ""}

    _fake_connector_ssh.sbatch = ""
    monkeypatch.setattr(submission, "connector_ssh", _fake_connector_ssh)
    monkeypatch.setattr(submission, "connector_stage_archive",
                        lambda *a, **k: {"ok": True, "stdout": "", "stderr": ""})
    monkeypatch.setattr(submission, "connector_slurm_submit",
                        lambda *a, **k: {"ok": True, "submitted": True, "jobid": "42"})

    ex = tmp_path / "ice-shelf"
    ex.mkdir()
    (ex / "ice-shelf.py").write_text("import icepack\n")

    submission.submit_remote_icesheets_via_connector(
        session_id="s", host="login", user="u", port=22,
        remote_base_dir="~/base", remote_tag="icesheets",
        backend="container", model="icepack",
        example_dir=str(ex), exec_dir=str(ex),
        image_uri="/shared/images/combined.sif", container_source="local",
        spack_enable=False, spack_repo_url="", spack_dirname="ICESEE-Spack",
        spack_install_if_needed=False, spack_install_mode="",
        spack_slurm_dir="", spack_pmix_dir="",
        slurm_time="01:00:00", slurm_job_name="ICEPACK", slurm_nodes=1,
        slurm_ntasks=4, slurm_tpn=4, slurm_part="cpu", slurm_mem="16G",
        slurm_account="", slurm_mail="", test_mode=False, run_file="ice-shelf.py",
        matlab_license=get_compute_profile("pace").matlab_license_config(),
    )
    txt = _fake_connector_ssh.sbatch
    assert "cryostack_icepack_postprocess.py" in txt
    assert "with-issm matlab" not in txt
