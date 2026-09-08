"""AWSDriver.bootstrap must not lose progress on a stage failure: it returns a
structured partial result (per-row status + sanitized reason) instead of
raising, so the UI shows what was actually attempted and the Run Log carries
the reason.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.drivers.aws.driver import AWSDriver, _redact


class _Account:
    authenticated = True


class _Storage:
    created = True
    bucket = "cryostack-runs-774888247882"


class _Caps:
    authenticated = True
    storage_ready = False
    registry_ready = False
    batch_ready = False
    network_ready = False
    iam_ready = False


def _driver(**stage_impls):
    d = AWSDriver(region="us-east-2", credentials={"AWS_ACCESS_KEY_ID": "ASIA_X",
                                                  "AWS_SECRET_ACCESS_KEY": "s",
                                                  "AWS_SESSION_TOKEN": "t"})
    d.account = lambda: _Account()
    d.capabilities = lambda: _Caps()
    d.prepare_storage = stage_impls.get("storage", lambda *, bucket=None: _Storage())
    d.network = stage_impls.get("network", lambda: type("N", (), {
        "vpc_id": "vpc-1", "subnet_ids": ["s-1"], "security_group_ids": ["sg-1"]})())
    d.prepare_registry = stage_impls.get(
        "registry", lambda *, include_icepack=False, include_icesee=False: type("R", (), {
            "resources": None, "created": [], "reused": ["cryostack-issm"]})())
    d.prepare_batch = stage_impls.get("batch", lambda **kw: type("B", (), {
        "resources": type("X", (), {"compute_environment": "ce", "job_queue": "q",
                                    "issm_job_definition": "jd"})(),
        "created": [], "updated": [], "reused": [], "skipped": [], "messages": [],
        "image_delivery": None})())
    return d


def test_storage_failure_aborts_and_reports_only_storage_as_failed(monkeypatch):
    import cryostack_src.cloud.drivers.aws.driver as drv
    monkeypatch.setattr(drv, "ensure_iam_resources", lambda *a, **k: pytest.fail(
        "IAM must not be attempted after storage fails"))

    def _boom(*, bucket=None):
        raise RuntimeError(
            "An error occurred (AccessDenied) when calling the CreateBucket "
            "operation: session token FwoGZXIvYXdzEExampleTokenValue"
        )

    d = _driver(storage=_boom)
    result = d.bootstrap(bucket="cryostack-runs-774888247882")

    assert result["success"] is False
    rs = result["row_status"]
    assert rs == {"account": "connected", "storage": "failed",
                  "registry": "not_attempted", "compute": "not_attempted"}
    joined = "\n".join(result["messages"])
    assert "stage: storage" in joined
    assert "AccessDenied" in joined                       # useful detail kept
    assert "FwoGZXIvYXdzEE" not in joined                 # session token redacted
    assert "<redacted>" in joined


def test_iam_failure_marks_compute_not_registry(monkeypatch):
    import cryostack_src.cloud.drivers.aws.driver as drv

    def _iam_boom(*a, **k):
        raise RuntimeError("AccessDenied on iam:CreateRole")

    monkeypatch.setattr(drv, "ensure_iam_resources", _iam_boom)
    d = _driver()
    result = d.bootstrap(bucket="cryostack-runs-774888247882")

    rs = result["row_status"]
    assert rs["account"] == "connected"
    assert rs["storage"] == "ready"
    assert rs["compute"] == "failed"        # IAM is a compute prerequisite
    assert rs["registry"] == "not_attempted"


def test_full_success_returns_ready_row_status(monkeypatch):
    import cryostack_src.cloud.drivers.aws.driver as drv
    monkeypatch.setattr(drv, "ensure_iam_resources", lambda *a, **k: type("I", (), {
        "resources": type("R", (), {"job_role": "jr", "ecs_execution_role": "er"})(),
        "created": [], "reused": ["job_role"]})())

    class _CapsOK(_Caps):
        storage_ready = True
        registry_ready = True
        batch_ready = True
        network_ready = True
        iam_ready = True

    d = _driver()
    d.capabilities = lambda: _CapsOK()
    result = d.bootstrap(bucket="cryostack-runs-774888247882")
    assert result["success"] is True
    assert result["row_status"] == {"account": "connected", "storage": "ready",
                                    "registry": "ready", "compute": "ready"}


# -- Icepack Cloud Execution checkpoint -----------------------------------
def test_bootstrap_prepares_both_models_registry_and_batch(monkeypatch):
    """Prepare Cloud (bootstrap) must request BOTH models' resources -- this
    is the ONE call site that opts into Icepack; every other caller of
    prepare_registry/prepare_batch keeps the old ISSM-only default."""
    import cryostack_src.cloud.drivers.aws.driver as drv
    monkeypatch.setattr(drv, "ensure_iam_resources", lambda *a, **k: type("I", (), {
        "resources": type("R", (), {"job_role": "jr", "ecs_execution_role": "er"})(),
        "created": [], "reused": ["job_role"]})())

    class _CapsOK(_Caps):
        storage_ready = True
        registry_ready = True
        batch_ready = True
        network_ready = True
        iam_ready = True

    seen = {}

    def registry_spy(*, include_icepack=False, include_icesee=False):
        seen["registry_include_icepack"] = include_icepack
        seen["registry_include_icesee"] = include_icesee
        return type("R", (), {"resources": None, "created": [], "reused": ["cryostack-issm"]})()

    def batch_spy(**kw):
        seen["batch_include_icepack"] = kw.get("include_icepack")
        seen["batch_include_icesee"] = kw.get("include_icesee")
        return type("B", (), {
            "resources": type("X", (), {"compute_environment": "ce", "job_queue": "q",
                                        "issm_job_definition": "jd"})(),
            "created": [], "updated": [], "reused": [], "skipped": [], "messages": [],
            "image_delivery": None})()

    d = _driver(registry=registry_spy, batch=batch_spy)
    d.capabilities = lambda: _CapsOK()
    result = d.bootstrap(bucket="cryostack-runs-774888247882")

    assert result["success"] is True
    assert seen["registry_include_icepack"] is True
    assert seen["batch_include_icepack"] is True


# -- ICESEE Cloud Execution checkpoint ------------------------------------
def test_bootstrap_also_prepares_icesee_registry_and_batch(monkeypatch):
    """Prepare Cloud (bootstrap) must request ICESEE's resources too, the
    SAME unconditional way it already does for Icepack -- this is not a
    separate Prepare Cloud implementation, just a third opt-in on the one
    existing call site."""
    import cryostack_src.cloud.drivers.aws.driver as drv
    monkeypatch.setattr(drv, "ensure_iam_resources", lambda *a, **k: type("I", (), {
        "resources": type("R", (), {"job_role": "jr", "ecs_execution_role": "er"})(),
        "created": [], "reused": ["job_role"]})())

    class _CapsOK(_Caps):
        storage_ready = True
        registry_ready = True
        batch_ready = True
        network_ready = True
        iam_ready = True

    seen = {}

    def registry_spy(*, include_icepack=False, include_icesee=False):
        seen["registry_include_icesee"] = include_icesee
        return type("R", (), {"resources": None, "created": [], "reused": ["cryostack-issm"]})()

    def batch_spy(**kw):
        seen["batch_include_icesee"] = kw.get("include_icesee")
        return type("B", (), {
            "resources": type("X", (), {"compute_environment": "ce", "job_queue": "q",
                                        "issm_job_definition": "jd"})(),
            "created": [], "updated": [], "reused": [], "skipped": [], "messages": [],
            "image_delivery": None})()

    d = _driver(registry=registry_spy, batch=batch_spy)
    d.capabilities = lambda: _CapsOK()
    result = d.bootstrap(bucket="cryostack-runs-774888247882")

    assert result["success"] is True
    assert seen["registry_include_icesee"] is True
    assert seen["batch_include_icesee"] is True


def test_redact_helper_scrubs_secret_shaped_text():
    assert _redact("key AKIAIOSFODNN7EXAMPLE here") == "key <redacted> here"
    assert _redact("plain provisioning message") == "plain provisioning message"
