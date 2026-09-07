"""C7.1 -- security invariants for the assumed-role credential path."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.connect import (
    AWSConnection,
    AWSExecutionContext,
    assert_no_aws_secrets,
    redact_aws_secrets,
)
from cryostack_src.cloud.connect.redaction import AWSSecretLeak
from cryostack_src.cloud.drivers.aws.auth import aws_command, run_aws
from cryostack_src.cloud.drivers.aws.models import AWSConfig

TEMP_ENV = {
    "AWS_ACCESS_KEY_ID": "ASIA_TEMP",
    "AWS_SECRET_ACCESS_KEY": "temp-secret",
    "AWS_SESSION_TOKEN": "temp-token",
}


def _ctx() -> AWSExecutionContext:
    return AWSExecutionContext(
        account_id="774888247882",
        region="us-east-2",
        role_arn="arn:aws:iam::774888247882:role/CryoStackExecutionRole",
        external_id="cryostack:alice:xyz",
        _credentials=dict(TEMP_ENV),
    )


def test_redaction_scrubs_a_raw_assume_role_response():
    raw = {
        "Credentials": {
            "AccessKeyId": "ASIA_TEMP",
            "SecretAccessKey": "temp-secret",
            "SessionToken": "temp-token",
        },
        "AssumedRoleUser": {"Arn": "arn:aws:sts::774888247882:assumed-role/x/y"},
    }
    safe = redact_aws_secrets(raw)
    text = repr(safe)
    assert "temp-secret" not in text and "temp-token" not in text
    assert safe["AssumedRoleUser"]["Arn"].endswith("x/y")  # non-secret preserved


def test_assert_no_aws_secrets_fails_closed_on_a_persist_attempt():
    with pytest.raises(AWSSecretLeak):
        assert_no_aws_secrets({"AWS_SECRET_ACCESS_KEY": "temp-secret"})
    # a redacted structure is allowed through
    assert_no_aws_secrets(redact_aws_secrets({"AWS_SESSION_TOKEN": "temp-token"}))


def test_connection_record_can_never_carry_a_secret_field():
    conn = AWSConnection(connection_id="c1", external_id="e1", region="us-east-2")
    assert_no_aws_secrets(conn.to_dict(), context="connection")  # must not raise
    # no field holds a secret VALUE. matlab_license_secret_arn is an
    # explicit exception: it holds an AWS Secrets Manager *ARN* (a
    # non-secret identifier -- the license value stays in the user's
    # own account and never reaches CryoStack).
    _ok = {"matlab_license_secret_arn"}
    assert not any(
        ("secret" in f.lower() or "token" in f.lower()) and f not in _ok
        for f in AWSConnection.__dataclass_fields__
    )
    conn2 = conn.with_matlab_license_secret(
        "arn:aws:secretsmanager:us-east-2:123456789012:secret:x-AbCdEf")
    assert_no_aws_secrets(conn2.to_dict(), context="connection")  # ARN is not a secret


def test_context_does_not_serialise_and_repr_is_redacted():
    ctx = _ctx()
    assert not hasattr(ctx, "to_dict")
    blob = f"{ctx!r} {ctx} {vars(ctx).get('account_id')}"
    assert "temp-secret" not in blob and "temp-token" not in blob


def test_aws_config_credentials_are_repr_suppressed():
    cfg = AWSConfig(region="us-east-2", credentials=dict(TEMP_ENV))
    assert "temp-secret" not in repr(cfg)
    assert "temp-token" not in repr(cfg)


def test_assumed_role_config_drops_profile_and_ambient_env(monkeypatch):
    """`run_aws` with an assumed-role config must not leak an ambient key or a
    profile into the child `aws` process."""
    monkeypatch.setenv("AWS_PROFILE", "dev")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA_AMBIENT")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ambient-secret")

    captured = {}

    def fake_run(cmd, capture_output, text, env):
        captured["cmd"] = cmd
        captured["env"] = env

        class R:
            returncode = 0
            stdout = "{}"
            stderr = ""

        return R()

    monkeypatch.setattr("cryostack_src.cloud.drivers.aws.auth.subprocess.run", fake_run)

    cfg = AWSConfig(region="us-east-2", profile="dev", credentials=dict(TEMP_ENV))
    run_aws(cfg, ["sts", "get-caller-identity"])

    assert "--profile" not in captured["cmd"]
    env = captured["env"]
    assert env["AWS_ACCESS_KEY_ID"] == "ASIA_TEMP"
    assert env["AWS_SECRET_ACCESS_KEY"] == "temp-secret"
    assert env["AWS_SESSION_TOKEN"] == "temp-token"
    assert "AWS_PROFILE" not in env


def test_developer_mode_config_still_uses_profile_and_ambient_env(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text, env):
        captured["cmd"] = cmd
        captured["env"] = env

        class R:
            returncode = 0
            stdout = "{}"
            stderr = ""

        return R()

    monkeypatch.setattr("cryostack_src.cloud.drivers.aws.auth.subprocess.run", fake_run)
    run_aws(AWSConfig(region="us-east-2", profile="dev"), ["sts", "get-caller-identity"])
    assert "--profile" in captured["cmd"] and "dev" in captured["cmd"]
    assert captured["env"] is None  # inherit the parent environment unchanged
