"""ICESEE Cloud execution adapter (icesee_jupyter_book/core/
cloud_bridge_adapter.py) -- Step 1-3 of the ICESEE<->CryoLauncher cloud
convergence (overnight/AUDIT_icesee_cloud_convergence.md).

Parity tests: submit still issues the EXACT same AWS CLI calls as the
legacy submit_cloud_example path (characterization against
test_cloud_runner.py's own assertions), while status/terminate now flow
through the real, hardened CloudBackend/AWSDriver/legacy aws_batch
lifecycle instead of ICESEE's own aws_batch_status. No real AWS CLI is
ever invoked -- every call takes/threads an injectable ``aws`` transport.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.core.cloud_bridge_adapter import (
    IceseeCloudBridgeConfig,
    build_icesee_cloud_bridge,
    icesee_cloud_status,
    icesee_cloud_terminate,
    submit_icesee_cloud_run,
)


class _FakeAWS:
    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def __call__(self, config, arguments):
        self.calls.append((config, list(arguments)))
        if self._responses:
            return self._responses.pop(0)
        return (0, "{}", "")


def test_config_rejects_a_missing_region():
    with pytest.raises(ValueError, match="region"):
        IceseeCloudBridgeConfig(region="")


def test_submit_preserves_icesees_exact_upload_and_env_var_contract(tmp_path, monkeypatch):
    example_dir = tmp_path / "lorenz96"
    example_dir.mkdir()
    (example_dir / "run_da_lorenz96.py").write_text("# entry\n")
    monkeypatch.setattr(
        "icesee_jupyter_book.core.cloud_runner.find_run_script",
        lambda cfg: example_dir / "run_da_lorenz96.py",
    )

    fake = _FakeAWS(responses=[
        (0, '{"Account": "1"}', ""),
        (0, "", ""), (0, "", ""),
        (0, json.dumps({"jobId": "job-xyz"}), ""),
    ])
    creds = {"AWS_ACCESS_KEY_ID": "a", "AWS_SECRET_ACCESS_KEY": "b",
             "AWS_SESSION_TOKEN": "c"}
    cfg = IceseeCloudBridgeConfig(region="us-east-2", credentials=creds, aws=fake)
    bridge = build_icesee_cloud_bridge(cfg)

    result = submit_icesee_cloud_run(
        bridge,
        example_name="lorenz96", example_cfg={}, config={"k": "v"},
        s3_prefix="s3://bucket/runs", job_queue="q", job_definition="jd",
        job_name="icesee", run_dir_base=tmp_path / "runs", run_dir_name="r1",
    )

    assert result.success is True
    assert result.job_id == "job-xyz"
    assert result.working_directory.startswith("s3://bucket/runs/")
    assert result.metadata["provider"] == "aws"

    # every AWS call used the BYO credentials, never a profile -- and the
    # exact same argv shape test_cloud_runner.py's legacy-path test asserts
    submit_call = fake.calls[-1]
    assert submit_call[1][:2] == ["batch", "submit-job"]
    overrides = json.loads(submit_call[1][submit_call[1].index("--container-overrides") + 1])
    env = {e["name"]: e["value"] for e in overrides["environment"]}
    assert env["ICESEE_EXAMPLE"] == "lorenz96"
    assert env["ICESEE_RUN_SCRIPT"] == "run_da_lorenz96.py"
    for config, _args in fake.calls:
        assert config.credentials == creds
        assert config.profile is None

    # the local manifest directory is deterministic from run_dir_name,
    # exactly like the Local/Remote submission paths already compute it
    from icesee_jupyter_book.core.local_runner import run_dir as compute_run_dir
    expected_rd = compute_run_dir(tmp_path / "runs", "r1")
    assert expected_rd.is_dir()
    assert (expected_rd / "params.yaml").is_file()


def test_status_flows_through_the_real_hardened_driver_not_icesees_own(monkeypatch):
    """Status must reach cryostack_src.cloud.legacy.aws_batch.batch_status
    (via CloudBackend/AWSDriver), NOT icesee's own aws_batch_status."""
    import cryostack_src.cloud.legacy.aws_batch as legacy_batch

    calls = []

    class _FakeCompleted:
        def __init__(self, stdout):
            self.returncode, self.stdout, self.stderr = 0, stdout, ""

    class _FakeSubprocess:
        @staticmethod
        def run(argv, **kwargs):
            calls.append({"argv": argv, "env": kwargs.get("env")})
            return _FakeCompleted(json.dumps(
                {"jobs": [{"status": "RUNNING", "statusReason": ""}]}))

    monkeypatch.setattr(legacy_batch, "subprocess", _FakeSubprocess)

    creds = {"AWS_ACCESS_KEY_ID": "a", "AWS_SECRET_ACCESS_KEY": "b",
             "AWS_SESSION_TOKEN": "c"}
    cfg = IceseeCloudBridgeConfig(region="eu-west-1", credentials=creds)
    bridge = build_icesee_cloud_bridge(cfg)

    status = icesee_cloud_status(bridge, job_id="job-123")

    assert status.state == "running"
    assert status.raw_state == "RUNNING"
    assert status.metadata["region"] == "eu-west-1"     # the region bug fix
    (call,) = calls
    assert "describe-jobs" in call["argv"]
    assert "--region" in call["argv"] and "eu-west-1" in call["argv"]
    assert call["env"]["AWS_ACCESS_KEY_ID"] == "a"
    assert "AWS_PROFILE" not in call["env"]


def test_terminate_flows_through_the_real_hardened_driver(monkeypatch):
    import cryostack_src.cloud.legacy.aws_batch as legacy_batch

    calls = []

    class _FakeCompleted:
        def __init__(self, stdout):
            self.returncode, self.stdout, self.stderr = 0, stdout, ""

    class _FakeSubprocess:
        @staticmethod
        def run(argv, **kwargs):
            calls.append(argv)
            if "describe-jobs" in argv:
                return _FakeCompleted(json.dumps({"jobs": [{"status": "RUNNING"}]}))
            return _FakeCompleted("")

    monkeypatch.setattr(legacy_batch, "subprocess", _FakeSubprocess)

    cfg = IceseeCloudBridgeConfig(region="us-east-2")
    bridge = build_icesee_cloud_bridge(cfg)

    result = icesee_cloud_terminate(bridge, job_id="job-123")

    assert result["action"] == "terminated"
    assert any("terminate-job" in c for c in calls)


def test_a_missing_job_never_reaches_icesees_own_status_function():
    """Static confirmation: the adapter module never imports ICESEE's own
    aws_batch_status/terminate_cloud_job -- status/terminate genuinely go
    through the shared lifecycle, not a re-wrapped legacy call."""
    src = Path(__file__).resolve().parents[1].joinpath("cloud_bridge_adapter.py").read_text()
    assert "aws_batch_status" not in src
    assert "terminate_cloud_job" not in src
