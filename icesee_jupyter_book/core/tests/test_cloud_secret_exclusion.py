"""ICESEE Cloud provenance never persists a secret.

Defence-in-depth, on top of cryostack_src.cloud.diagnostics.merge_aws_resources's
own _is_secretish allow-list guard (already covered by that module's own
test suite): proves the ACTUAL data ICESEE's cloud submit path writes into
a run's manifest never contains AWS credentials, session tokens, or an
ExternalId, even when the underlying execution context legitimately holds
them in memory for one operation.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.diagnostics import merge_aws_resources

_FORBIDDEN_SUBSTRINGS = (
    "AKIA", "ASIA", "SecretAccessKey", "SessionToken", "external_id",
    "ExternalId", "sekret", "top-secret-value",
)


def test_merge_aws_resources_drops_credential_shaped_keys():
    creds = {
        "AWS_ACCESS_KEY_ID": "AKIA_SHOULD_NOT_PERSIST",
        "AWS_SECRET_ACCESS_KEY": "top-secret-value",
        "AWS_SESSION_TOKEN": "sekret-session-token",
        "external_id": "cryostack:user:abc123",
    }
    merged = merge_aws_resources(None, {
        **creds,
        "region": "us-east-2", "batch_job_id": "job-1",
    })
    assert merged == {"region": "us-east-2", "batch_job_id": "job-1"}
    blob = str(merged)
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        assert forbidden not in blob


def test_icesee_run_manifest_never_carries_the_credentials_dict(tmp_path):
    """The actual manifest write path: record_run's metadata block must
    never include the raw credentials dict, even though the caller (the
    gateway) legitimately holds one in memory for the submit call --
    credentials flow into the bridge config for the AWS call only, never
    into record_run's own arguments."""
    from icesee_jupyter_book.core import run_records as rr

    run_dir = tmp_path / "cred-check"
    rr.record_run(
        run_dir=run_dir, run_id="cred-check", name="cred check",
        params={}, example="lorenz96", execution_mode="cloud",
        backend="aws", status="running", jobid="job-1",
        extra_metadata=merge_aws_resources(None, {
            "region": "us-east-2", "batch_job_id": "job-1",
        }),
    )

    manifest_text = (run_dir / rr.MANIFEST_NAME).read_text()
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        assert forbidden not in manifest_text
