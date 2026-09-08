"""ICESEE cloud submission (core/cloud_runner.py), now credential-aware.

Before this, AWSBatchConfig had no credentials field at all and every AWS
CLI subprocess call inherited the full ambient environment unconditionally
-- there was no way to route a BYO-AWS assumed-role session through it, and
no defence against an ambient AWS_* var leaking through even once one was
wired in some other way. This delegates the actual AWS CLI invocation to
cryostack_src.cloud.legacy.aws_batch's AWSConfig/run_aws -- the SAME
credential-stripping logic CryoLauncher's own AWSDriver.status/logs/
terminate use (already covered end-to-end by
cryostack_src/cloud/tests/test_aws_batch_legacy_credentials.py) -- while
ICESEE's own upload/submit contract (params.yaml, cloud_manifest.json,
ICESEE_S3_RUN/ICESEE_EXAMPLE/ICESEE_RUN_SCRIPT) stays byte-identical.

No real AWS CLI is ever invoked here: every AWS-touching call takes an
injectable ``aws`` callable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.core.cloud_runner import (
    MAX_SINGLE_TASK_MPI_RANKS,
    AWSBatchConfig,
    aws_batch_status,
    aws_batch_submit,
    aws_test,
    build_icesee_container_env,
    submit_cloud_example,
    terminate_cloud_job,
)


class _FakeAWS:
    """Records every (config, arguments) call; returns canned responses."""

    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def __call__(self, config, arguments):
        self.calls.append((config, list(arguments)))
        if self._responses:
            return self._responses.pop(0)
        return (0, "{}", "")


def test_aws_test_passes_the_configs_credentials_through_to_run_aws():
    fake = _FakeAWS(responses=[(0, '{"Account": "774888247882"}', "")])
    creds = {"AWS_ACCESS_KEY_ID": "AKIA-temp", "AWS_SECRET_ACCESS_KEY": "s",
             "AWS_SESSION_TOKEN": "t"}
    cfg = AWSBatchConfig(region="us-east-2", profile="ignored-when-creds-set",
                         credentials=creds)
    aws_test(cfg, aws=fake)
    (config, args) = fake.calls[0]
    assert args == ["sts", "get-caller-identity"]
    assert config.credentials == creds
    assert config.region == "us-east-2"


def test_aws_test_raises_on_a_nonzero_exit(monkeypatch):
    fake = _FakeAWS(responses=[(255, "", "not authorized")])
    with pytest.raises(RuntimeError, match="not authorized"):
        aws_test(AWSBatchConfig(), aws=fake)


def test_aws_batch_submit_issues_the_documented_argv_shape(tmp_path):
    (tmp_path / "params.yaml").write_text("a: 1\n")
    fake = _FakeAWS(responses=[
        (0, "", ""),                                   # s3 cp params.yaml
        (0, "", ""),                                   # s3 cp cloud_manifest.json
        (0, json.dumps({"jobId": "job-123"}), ""),      # batch submit-job
    ])
    cfg = AWSBatchConfig(
        region="us-east-2", s3_prefix="s3://bucket/prefix",
        job_queue="q", job_definition="jd:3", job_name="icesee",
    )
    resp = aws_batch_submit(cfg, tmp_path, "lorenz96", "run_da_lorenz96.py", aws=fake)

    assert resp["batch_job_id"] == "job-123"
    assert resp["s3_run"].startswith("s3://bucket/prefix/")
    run_id = resp["run_id"]
    assert resp["s3_run"] == f"s3://bucket/prefix/{run_id}"

    upload_params, upload_manifest, submit = (c[1] for c in fake.calls)
    assert upload_params == ["s3", "cp", str(tmp_path / "params.yaml"),
                              f"{resp['s3_run']}/params.yaml"]
    assert upload_manifest[:2] == ["s3", "cp"]
    assert upload_manifest[-1] == f"{resp['s3_run']}/cloud_manifest.json"

    assert submit[:2] == ["batch", "submit-job"]
    assert "--job-name" in submit and f"icesee-{run_id}" in submit
    assert "--job-queue" in submit and "q" in submit
    assert "--job-definition" in submit and "jd:3" in submit
    overrides = json.loads(submit[submit.index("--container-overrides") + 1])
    env = {e["name"]: e["value"] for e in overrides["environment"]}
    assert env == {
        "ICESEE_S3_RUN": resp["s3_run"],
        "ICESEE_EXAMPLE": "lorenz96",
        "ICESEE_RUN_SCRIPT": "run_da_lorenz96.py",
    }

    manifest = json.loads((tmp_path / "cloud_manifest.json").read_text())
    assert manifest == {"run_id": run_id, "example": "lorenz96",
                         "run_script": "run_da_lorenz96.py"}


def test_aws_batch_submit_requires_s3_queue_and_job_definition(tmp_path):
    with pytest.raises(ValueError, match="s3_prefix/job_queue/job_definition"):
        aws_batch_submit(AWSBatchConfig(), tmp_path, "ex", "run.py", aws=_FakeAWS())


def test_aws_batch_status_maps_describe_jobs_output():
    fake = _FakeAWS(responses=[
        (0, json.dumps({"jobs": [{"status": "RUNNING", "statusReason": ""}]}), ""),
    ])
    result = aws_batch_status(AWSBatchConfig(), "job-123", aws=fake)
    assert result == {"status": "RUNNING", "reason": ""}
    (_, args) = fake.calls[0]
    assert args == ["batch", "describe-jobs", "--jobs", "job-123"]


def test_submit_cloud_example_end_to_end_with_credentials(tmp_path, monkeypatch):
    """The public entry point icesee_gateway.py actually calls: builds
    params.yaml, tests the connection, submits -- with BYO-AWS credentials
    threaded all the way through, never falling back to a profile."""
    from icesee_jupyter_book.core.example_discovery import find_run_script

    example_dir = tmp_path / "lorenz96"
    example_dir.mkdir()
    (example_dir / "run_da_lorenz96.py").write_text("# entry point\n")
    monkeypatch.setattr(
        "icesee_jupyter_book.core.cloud_runner.find_run_script",
        lambda cfg: example_dir / "run_da_lorenz96.py",
    )

    fake = _FakeAWS(responses=[
        (0, '{"Account": "1"}', ""),                    # aws_test
        (0, "", ""), (0, "", ""),                        # 2 s3 cp
        (0, json.dumps({"jobId": "job-xyz"}), ""),       # submit-job
    ])
    creds = {"AWS_ACCESS_KEY_ID": "a", "AWS_SECRET_ACCESS_KEY": "b",
             "AWS_SESSION_TOKEN": "c"}

    result = submit_cloud_example(
        example_name="lorenz96", example_cfg={}, config={"k": "v"},
        region="us-east-2", profile=None, credentials=creds,
        s3_prefix="s3://bucket/runs", job_queue="q", job_definition="jd",
        job_name="icesee", run_dir_base=tmp_path / "runs", run_dir_name="r1",
        aws=fake,
    )

    assert result.success is True
    assert result.batch_job_id == "job-xyz"
    assert (result.run_dir / "params.yaml").is_file()
    # every AWS call carried the BYO credentials, never a profile
    for config, _args in fake.calls:
        assert config.credentials == creds
        assert config.profile is None


def test_terminate_cloud_job_reaches_the_batch_call_with_credentials(monkeypatch):
    """No injectable ``aws`` hook exists on the shared terminate_batch_job,
    so this patches subprocess at the shared module -- the same pattern
    cryostack_src/cloud/tests/test_aws_batch_legacy_credentials.py uses."""
    import cryostack_src.cloud.legacy.aws_batch as legacy_batch

    calls = []

    class _FakeCompleted:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    class _FakeSubprocess:
        @staticmethod
        def run(argv, **kwargs):
            calls.append({"argv": argv, "env": kwargs.get("env")})
            if "describe-jobs" in argv:
                return _FakeCompleted(json.dumps({"jobs": [{"status": "RUNNABLE"}]}))
            return _FakeCompleted("")

    monkeypatch.setattr(legacy_batch, "subprocess", _FakeSubprocess)

    creds = {"AWS_ACCESS_KEY_ID": "a", "AWS_SECRET_ACCESS_KEY": "b",
             "AWS_SESSION_TOKEN": "c"}
    cfg = AWSBatchConfig(region="us-east-2", credentials=creds)
    result = terminate_cloud_job(cfg, "job-123")

    assert result["action"] == "cancelled"
    describe_call, cancel_call = calls
    assert describe_call["argv"][0] == "aws"
    assert "describe-jobs" in describe_call["argv"]
    assert "cancel-job" in cancel_call["argv"]
    # BYO credentials reached the subprocess env, not a profile
    assert cancel_call["env"]["AWS_ACCESS_KEY_ID"] == "a"
    assert "AWS_PROFILE" not in cancel_call["env"]


# ── MPI-aware container overrides ────────────────────────────────────────
def test_build_icesee_container_env_carries_the_mpirun_contract():
    env = build_icesee_container_env(
        s3_run="s3://bucket/prefix/r1", example_name="lorenz96",
        run_script_name="run_da_lorenz96.py", np=8, nens=20, model_nprocs=2,
    )
    by_name = {e["name"]: e["value"] for e in env}
    assert by_name["ICESEE_S3_RUN"] == "s3://bucket/prefix/r1"
    assert by_name["ICESEE_EXAMPLE"] == "lorenz96"
    assert by_name["ICESEE_RUN_SCRIPT"] == "run_da_lorenz96.py"
    assert by_name["ICESEE_NP"] == "8"
    assert by_name["ICESEE_NENS"] == "20"
    assert by_name["ICESEE_MODEL_NPROCS"] == "2"


def test_build_icesee_container_env_omits_mpi_vars_when_not_supplied():
    """Never fabricated: a caller that has no MPI parameters (np=None) gets
    exactly the three identity env vars, nothing invented."""
    env = build_icesee_container_env(
        s3_run="s3://bucket/prefix/r1", example_name="lorenz96",
        run_script_name="run_da_lorenz96.py",
    )
    names = {e["name"] for e in env}
    assert names == {"ICESEE_S3_RUN", "ICESEE_EXAMPLE", "ICESEE_RUN_SCRIPT"}


def test_aws_batch_submit_threads_mpi_params_into_the_real_submission(tmp_path):
    (tmp_path / "params.yaml").write_text("a: 1\n")
    fake = _FakeAWS(responses=[
        (0, "", ""), (0, "", ""),
        (0, json.dumps({"jobId": "job-mpi"}), ""),
    ])
    cfg = AWSBatchConfig(
        region="us-east-2", s3_prefix="s3://bucket/prefix",
        job_queue="q", job_definition="jd",
    )
    aws_batch_submit(
        cfg, tmp_path, "lorenz96", "run_da_lorenz96.py",
        np=8, nens=20, model_nprocs=2, aws=fake,
    )
    submit_call = fake.calls[-1][1]
    overrides = json.loads(submit_call[submit_call.index("--container-overrides") + 1])
    env = {e["name"]: e["value"] for e in overrides["environment"]}
    assert env["ICESEE_NP"] == "8" and env["ICESEE_NENS"] == "20"
    assert env["ICESEE_MODEL_NPROCS"] == "2"


def test_submit_cloud_example_warns_when_np_exceeds_the_single_task_ceiling(tmp_path, monkeypatch):
    example_dir = tmp_path / "ex"
    example_dir.mkdir()
    (example_dir / "run.py").write_text("# entry\n")
    monkeypatch.setattr(
        "icesee_jupyter_book.core.cloud_runner.find_run_script",
        lambda cfg: example_dir / "run.py",
    )
    fake = _FakeAWS(responses=[
        (0, "{}", ""), (0, "", ""), (0, "", ""),
        (0, json.dumps({"jobId": "job-big"}), ""),
    ])
    result = submit_cloud_example(
        example_name="big-ensemble", example_cfg={}, config={},
        region="us-east-2", profile=None,
        s3_prefix="s3://bucket/runs", job_queue="q", job_definition="jd",
        job_name="icesee", np=MAX_SINGLE_TASK_MPI_RANKS + 4, nens=64,
        model_nprocs=1, run_dir_base=tmp_path / "runs", run_dir_name="r1",
        aws=fake,
    )
    assert any("exceeds" in m and "Fargate" in m for m in result.messages)
