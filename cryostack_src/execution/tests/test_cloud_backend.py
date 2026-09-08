"""CloudBackend (cryostack_src/execution/cloud.py) -- the strangler-migration
execution interface CloudBridge wraps. No real AWS is ever contacted here;
CloudManager.driver()/AWSDriver are exercised with a fake `aws` transport
via an injected submitter, or with a stubbed CloudManager for status.

Regression: status() defaulted its `region` keyword to the literal string
"us-east-2" instead of None, so `region or self.region` always picked the
hardcoded default and silently ignored a backend actually configured for a
different region -- every real call site (bridge.status(job_id=...)) omits
`region`, so this was live for any non-us-east-2 deployment. logs()/
terminate() already used the correct `None` default; only status() had
drifted.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.execution.cloud import CloudBackend


class _StubManager:
    def __init__(self):
        self.status_calls = []

    def status(self, **kwargs):
        self.status_calls.append(kwargs)
        return {"status": "RUNNING", "reason": ""}


def test_status_uses_the_backends_own_region_when_caller_omits_it():
    backend = CloudBackend(provider="aws", region="us-west-2")
    backend.manager = _StubManager()

    backend.status(job_id="job-1")

    assert backend.manager.status_calls[0]["region"] == "us-west-2"


def test_status_honours_an_explicitly_passed_region():
    backend = CloudBackend(provider="aws", region="us-west-2")
    backend.manager = _StubManager()

    backend.status(job_id="job-1", region="eu-central-1")

    assert backend.manager.status_calls[0]["region"] == "eu-central-1"


def test_status_metadata_region_matches_the_region_actually_queried():
    backend = CloudBackend(provider="aws", region="us-west-2")
    backend.manager = _StubManager()

    result = backend.status(job_id="job-1")

    assert result.metadata["region"] == "us-west-2"


def test_submit_normalizes_a_dict_result_from_a_legacy_submitter():
    """The exact shape ICESEE's CloudSubmitResult-as-dict / aws_batch_submit
    responses take."""
    def _submitter(**kwargs):
        return {
            "batch_job_id": "job-xyz", "s3_run": "s3://bucket/runs/r1",
            "run_id": "r1", "messages": ["submitted"],
        }

    backend = CloudBackend(provider="aws", region="us-east-2", submitter=_submitter)
    result = backend.submit(example_name="lorenz96")

    assert result.success is True
    assert result.job_id == "job-xyz"
    assert result.working_directory == "s3://bucket/runs/r1"
    assert result.output_directory == "s3://bucket/runs/r1/outputs"
    assert result.messages == ["submitted"]
    assert result.metadata["run_id"] == "r1"


def test_submit_normalizes_an_object_result_from_a_legacy_submitter():
    """ICESEE's actual CloudSubmitResult dataclass shape (attributes, not a
    dict) -- the getattr branch of CloudBackend.submit's normalization."""
    from dataclasses import dataclass

    @dataclass
    class _Result:
        success: bool
        batch_job_id: str
        s3_run: str
        run_id: str
        messages: list

    def _submitter(**kwargs):
        return _Result(success=True, batch_job_id="job-abc",
                       s3_run="s3://bucket/runs/r2", run_id="r2",
                       messages=["ok"])

    backend = CloudBackend(provider="aws", region="us-east-2", submitter=_submitter)
    result = backend.submit(example_name="lorenz96")

    assert result.job_id == "job-abc"
    assert result.working_directory == "s3://bucket/runs/r2"
    assert result.metadata["run_id"] == "r2"
