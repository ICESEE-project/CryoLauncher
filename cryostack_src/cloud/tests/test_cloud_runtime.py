"""Cloud Commit 3 -- the generic cloud runtime contract (descriptor + runner)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import json

from cryostack_src.cloud.runtime import (
    BATCH_CONTAINER_OVERRIDE_LIMIT,
    ICEPACK_EXPORT_FILENAME,
    ICEPACK_POSTPROCESS_FILENAME,
    ICEPACK_RUNNER_FILENAME,
    RESULT_CONTRACT_VERSION,
    RUN_DESCRIPTOR_NAME,
    SUPPORTED_CLOUD_MODELS,
    CloudRuntimeError,
    build_cloud_runner,
    build_run_descriptor,
    cloud_run_command,
    descriptor_is_clean,
    icepack_postprocess_extra_files,
    is_supported_cloud_model,
)


# ── execution descriptor ─────────────────────────────────────────────────
def test_descriptor_carries_only_execution_inputs():
    d = build_run_descriptor(model="ISSM", run_target="runme.m")
    assert d == {
        "schema": "cryostack.cloud.run", "version": 1, "model": "issm",
        "run_target": "runme.m", "working_directory": ".",
        "result_contract_version": RESULT_CONTRACT_VERSION,
    }
    assert descriptor_is_clean(d) is True


@pytest.mark.parametrize("bad", [
    {"run_target": "/abs/runme.m"},
    {"run_target": "../escape.m"},
    {"run_target": ""},
    {"model": ""},
    {"run_target": "runme.m", "working_directory": "/abs"},
    {"run_target": "runme.m", "working_directory": "../up"},
])
def test_descriptor_rejects_unsafe_inputs(bad):
    kw = {"model": "issm", "run_target": "runme.m"}
    kw.update(bad)
    with pytest.raises(CloudRuntimeError):
        build_run_descriptor(**kw)


def test_descriptor_is_clean_flags_secrets_and_paths():
    assert descriptor_is_clean({"x": "/home/alice/thing"}) is False
    assert descriptor_is_clean({"x": "MLM_LICENSE_FILE=1711@server"}) is False
    assert descriptor_is_clean({"x": "aws_secret_access_key"}) is False
    assert descriptor_is_clean({"model": "issm", "run_target": "runme.m"}) is True


def test_supported_models():
    assert SUPPORTED_CLOUD_MODELS == ("issm", "icepack")
    assert is_supported_cloud_model("ISSM") is True
    assert is_supported_cloud_model("Icepack") is True
    assert is_supported_cloud_model("firedrake") is False


# ── the runner ───────────────────────────────────────────────────────────
def test_runner_is_env_driven_and_backend_neutral():
    r = build_cloud_runner()
    for var in ("CRYOSTACK_S3_RUN", "CRYOSTACK_MODEL", "CRYOSTACK_RUN_TARGET"):
        assert var in r
    # three phases: input sync -> model runtime -> output sync
    assert 'aws s3 sync "${CRYOSTACK_S3_RUN}/input/"' in r
    assert 'aws s3 sync "${OUTPUTS}/" "${CRYOSTACK_S3_RUN}/outputs/"' in r
    # nothing about which execution mode / SIF / cluster produced the run
    for token in ("apptainer", "srun", "sbatch", "ssh", "rsync", "spack"):
        assert token not in r


def test_runner_issm_runs_target_then_postprocess():
    r = build_cloud_runner()
    assert "with-issm matlab" in r
    assert "run('${RUN_TARGET}')" in r
    assert "run('${WORKDIR}/postprocess_icesee.m')" in r


# -- Icepack Cloud Execution checkpoint -----------------------------------
def test_runner_icepack_runs_via_the_staged_runner_then_collector():
    """The generic runner INVOKES the staged Icepack helpers by filename
    (cryostack_icepack_runner.py -> headless run + figure capture + export;
    cryostack_icepack_postprocess.py -> stdlib collector) -- it must never
    embed their source text. That embedding is exactly what previously blew
    the runner past AWS Batch's 8192-character container-overrides limit."""
    r = build_cloud_runner()
    assert f'"${{WORKDIR}}/{ICEPACK_RUNNER_FILENAME}"' in r
    assert f'if [ -f "${{WORKDIR}}/{ICEPACK_RUNNER_FILENAME}" ]; then' in r
    # notebook examples are converted first, same rule as local/remote
    assert "jupyter nbconvert --to script" in r
    assert f'if [ -f "${{WORKDIR}}/{ICEPACK_POSTPROCESS_FILENAME}" ]; then' in r
    assert f'python3 "${{WORKDIR}}/{ICEPACK_POSTPROCESS_FILENAME}"' in r
    assert 'CRYOSTACK_RUN_DIR="${WORKDIR}"' in r
    # the helpers' OWN source text must never appear in the runner
    from cryostack_src.models.icepack.export import (
        export_module_source, runner_module_source,
    )
    from cryostack_src.models.icepack.postprocess import build_postprocess
    assert build_postprocess() not in r
    assert runner_module_source() not in r
    assert export_module_source() not in r
    # never the old deliberate block
    assert "Icepack cloud execution is not supported yet" not in r
    # no leftover substitution token
    assert "__CRYOSTACK" not in r


def test_runner_icepack_falls_back_to_a_bare_python_when_the_helper_is_absent():
    """A run that never staged the runner helper still executes the science
    -- just headless (MPLBACKEND=Agg) and without figure capture / export."""
    r = build_cloud_runner()
    assert 'MPLBACKEND=Agg with-icepack python "${SCRIPT}"' in r


def test_runner_icepack_postprocess_never_overrides_the_science_exit_code():
    lines = build_cloud_runner().splitlines()
    body = [l for l in lines if not l.lstrip().startswith("#")]
    icepack_block = "\n".join(body[body.index("  icepack)"):body.index("  *)")])
    assert "rc=$?" in icepack_block                       # captured from the model run
    # the postprocess invocation's own failure is swallowed by `||`, so it
    # can never clobber $rc
    assert f'python3 "${{WORKDIR}}/{ICEPACK_POSTPROCESS_FILENAME}" \\' in icepack_block
    assert "|| log" in icepack_block


def test_runner_icepack_skips_the_collector_gracefully_when_not_staged():
    """A run that predates this convention (or never staged the helper) must
    not hard-fail -- the invocation is skipped with a warning, same as every
    other best-effort step in the runner."""
    r = build_cloud_runner()
    assert "was not staged with this run's inputs; skipping" in r


# -- the actual AWS limit this checkpoint fixes ----------------------------
def test_runner_and_job_command_stay_safely_below_the_batch_override_limit():
    """The regression for the live failure itself: AWS Batch forwards a
    job's effective container command through an ECS RunTask override on
    every launch, capped at BATCH_CONTAINER_OVERRIDE_LIMIT (8192) chars --
    the SAME limit submit-job's own --container-overrides enforces. Before
    this fix, embedding the Icepack collector inline pushed the serialized
    command to 8278 characters (over the limit); it must now stay
    comfortably under it, with real headroom for future growth."""
    assert BATCH_CONTAINER_OVERRIDE_LIMIT == 8192
    r = build_cloud_runner()
    assert len(r) < BATCH_CONTAINER_OVERRIDE_LIMIT
    cmd = cloud_run_command()
    serialized = json.dumps(cmd)
    assert len(serialized) < BATCH_CONTAINER_OVERRIDE_LIMIT
    # real headroom, not a hair's-breadth pass -- catches the next helper
    # someone is tempted to embed inline before it blows the limit again
    assert len(serialized) < BATCH_CONTAINER_OVERRIDE_LIMIT - 2000
    # the runner still carries everything a run needs to be located/run
    for required in ("CRYOSTACK_S3_RUN", "CRYOSTACK_MODEL", "CRYOSTACK_RUN_TARGET"):
        assert required in r


def test_icepack_postprocess_extra_files_carries_the_real_helpers_under_the_expected_names():
    """The staging-side half of the contract: the SAME filenames the runner
    looks for, mapped to the actual helper sources (not stubs), and the SAME
    sources the Remote/SLURM path stages."""
    from cryostack_src.models.icepack.export import (
        export_module_source, runner_module_source,
    )
    from cryostack_src.models.icepack.postprocess import build_postprocess

    files = icepack_postprocess_extra_files()
    assert set(files) == {
        ICEPACK_RUNNER_FILENAME, ICEPACK_EXPORT_FILENAME, ICEPACK_POSTPROCESS_FILENAME,
    }
    assert files[ICEPACK_POSTPROCESS_FILENAME] == build_postprocess()
    assert files[ICEPACK_RUNNER_FILENAME] == runner_module_source()
    assert files[ICEPACK_EXPORT_FILENAME] == export_module_source()
    for text in files.values():
        assert len(text) > 500                                # the real thing, not a stub


def test_runner_propagates_true_exit_code_no_swallowing():
    lines = build_cloud_runner().splitlines()
    body = [l for l in lines if not l.lstrip().startswith("#")]
    joined = "\n".join(body)
    assert "|| true" not in joined                       # never swallow the science
    assert "rc=$?" in joined                             # capture the real code
    assert 'exit "${rc}"' in joined                      # ... and propagate it
    # the matlab invocation itself has no "|| true" / "; true" tail
    matlab_line = next(l for l in body if "with-issm matlab" in l)
    assert "true" not in matlab_line


def test_runner_uploads_outputs_even_on_failure():
    r = build_cloud_runner()
    # output sync is guarded only by "outputs dir exists", not by "rc == 0"
    idx_science = r.index("model runtime exit code")
    idx_upload = r.index('aws s3 sync "${OUTPUTS}/"')
    assert idx_upload > idx_science
    assert 'if [ -d "${OUTPUTS}" ]; then' in r


def test_runner_carries_no_license_value():
    r = build_cloud_runner()
    assert "1711@matlablic" not in r
    assert "MLM_LICENSE_FILE=" not in r                  # only ever from batch env


def test_runner_unsupported_model_errors_clearly():
    r = build_cloud_runner()
    assert 'fail 64 "unsupported model: ${CRYOSTACK_MODEL}"' in r
    # a genuinely unknown model still gets a clear error (icepack no longer does)
    assert 'unsupported model' in r


def test_cloud_run_command_wraps_the_runner():
    cmd = cloud_run_command()
    assert cmd[:2] == ["bash", "-c"]
    assert cmd[2] == build_cloud_runner()
