"""ISSM cloud MATLAB-license readiness seam.

CryoStack stores ONLY a non-secret AWS Secrets Manager ARN. The license
value (MLM_LICENSE_FILE = <port>@<host>, or a MathWorks token) stays in the
user's own account and never reaches CryoStack, git, the image, an S3 run
artifact, a manifest, a command preview, or a log. AWS Batch injects it into
the container at launch via containerProperties.secrets.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.connect.execution import CloudExecution
from cryostack_src.cloud.connect.models import AWSConnection
from cryostack_src.cloud.drivers.aws.batch_config import (
    container_properties_payload,
    job_definition_fingerprint,
)
from cryostack_src.cloud.matlab_license import (
    MATLAB_LICENSE_ENV,
    NOT_CONFIGURED,
    CloudMatlabLicense,
    assert_not_a_license_value,
    is_secret_arn,
    resolve_cloud_matlab_license,
)

_ARN = "arn:aws:secretsmanager:us-east-2:123456789012:secret:cryostack/issm-matlab-AbCdEf"


def _conn(**over):
    c = AWSConnection(connection_id="c1", external_id="e1", region="us-east-2")
    for k, v in over.items():
        c = c.__class__(**{**c.to_dict(), k: v})
    return c


# ── the seam: ARN only, never a value ──────────────────────────────────
def test_unconfigured_connection_is_not_ready():
    assert resolve_cloud_matlab_license(_conn()) == NOT_CONFIGURED
    assert NOT_CONFIGURED.configured is False
    assert NOT_CONFIGURED.batch_secrets_block() == []


def test_a_valid_secret_arn_makes_issm_runtime_configured():
    lic = resolve_cloud_matlab_license(_conn(matlab_license_secret_arn=_ARN))
    assert lic.configured and lic.mechanism == "secrets-manager"
    assert lic.secret_arn == _ARN
    assert lic.batch_secrets_block() == [
        {"name": MATLAB_LICENSE_ENV, "valueFrom": _ARN}]


def test_a_malformed_arn_is_treated_as_unconfigured_never_a_crash():
    for bad in ("not-an-arn", "arn:aws:s3:::bucket", "27000@license.example.com", ""):
        assert resolve_cloud_matlab_license(
            _conn(matlab_license_secret_arn=bad)) == NOT_CONFIGURED


def test_is_secret_arn():
    assert is_secret_arn(_ARN)
    assert not is_secret_arn("arn:aws:iam::123456789012:role/x")
    assert not is_secret_arn("27000@matlab.example.com")


def test_leak_guard_rejects_a_license_value():
    assert_not_a_license_value(_ARN)          # an ARN is fine
    assert_not_a_license_value("")            # empty is fine
    for value in ("27000@license.example.com", "MLM_LICENSE_FILE=1711@host",
                  "1711@matlablic.example.edu"):
        with pytest.raises(ValueError):
            assert_not_a_license_value(value)


# ── CloudExecution.matlab_license ──────────────────────────────────────
def test_cloud_execution_surfaces_license_state_non_secret():
    ex_none = CloudExecution(mode="developer", region="us-east-2")
    assert ex_none.matlab_license == NOT_CONFIGURED

    ex_byo = CloudExecution(mode="byo", region="us-east-2",
                            connection=_conn(matlab_license_secret_arn=_ARN))
    assert ex_byo.matlab_license.configured
    blob = json.dumps(ex_byo.matlab_license.as_public_dict())
    assert _ARN in blob                       # the ARN is fine to surface
    assert "@" not in blob.replace(_ARN, "")  # ... but no license VALUE shape


# ── the connection record persists an ARN, never a secret ─────────────
def test_connection_round_trips_the_arn_and_it_is_non_secret():
    from cryostack_src.cloud.connect.redaction import assert_no_aws_secrets

    c = _conn().with_matlab_license_secret(_ARN)
    d = c.to_dict()
    assert d["matlab_license_secret_arn"] == _ARN
    assert AWSConnection.from_dict(d).matlab_license_secret_arn == _ARN
    assert_no_aws_secrets(d, context="connection")           # ARN is not a secret
    assert_no_aws_secrets(c.to_public_dict(own=True), context="connection")


# ── job definition: secrets are ARN references, never values ──────────
def test_container_properties_payload_wires_the_secret_arn_reference():
    lic = CloudMatlabLicense(configured=True, mechanism="secrets-manager",
                             secret_arn=_ARN)
    cp = container_properties_payload(
        model="issm", image="repo@sha256:" + "a" * 64,
        job_role_arn="arn:aws:iam::123456789012:role/job",
        execution_role_arn="arn:aws:iam::123456789012:role/exec",
        region="us-east-2", secrets=lic.batch_secrets_block())
    assert cp["secrets"] == [{"name": "MLM_LICENSE_FILE", "valueFrom": _ARN}]
    # the fingerprint tracks it -> a license add/remove re-registers the job def
    fp = job_definition_fingerprint(container_properties=cp,
                                    timeout_seconds=3600, attempts=1)
    assert ("MLM_LICENSE_FILE", _ARN) in fp["secrets"]


def test_container_properties_payload_rejects_a_raw_value_in_valueFrom():
    with pytest.raises(ValueError):
        container_properties_payload(
            model="issm", image="repo@sha256:" + "a" * 64,
            job_role_arn="arn:aws:iam::123456789012:role/job",
            execution_role_arn="arn:aws:iam::123456789012:role/exec",
            region="us-east-2",
            secrets=[{"name": "MLM_LICENSE_FILE", "valueFrom": "27000@host"}])


def test_no_secrets_block_when_unconfigured():
    cp = container_properties_payload(
        model="issm", image="repo@sha256:" + "a" * 64,
        job_role_arn="arn:aws:iam::123456789012:role/job",
        execution_role_arn="arn:aws:iam::123456789012:role/exec",
        region="us-east-2", secrets=NOT_CONFIGURED.batch_secrets_block())
    assert "secrets" not in cp
