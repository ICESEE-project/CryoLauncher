"""Cloud Commit 3 -- pre-submit gates: no billable job for a misconfigured run."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.cloud.preflight import (
    assert_cloud_run_allowed,
    cloud_run_preflight,
)
from cryostack_src.cloud.runtime import CloudRuntimeError


def test_issm_without_a_cloud_matlab_license_is_blocked():
    reasons = cloud_run_preflight(model="issm", matlab_license_configured=False)
    assert reasons and "MATLAB license reachable from AWS" in reasons[0]
    assert "Secrets Manager" in reasons[0]
    with pytest.raises(CloudRuntimeError):
        assert_cloud_run_allowed(model="issm", matlab_license_configured=False)


def test_issm_with_a_configured_license_passes():
    assert cloud_run_preflight(model="issm", matlab_license_configured=True) == []
    assert_cloud_run_allowed(model="issm", matlab_license_configured=True)  # no raise


def test_icepack_needs_no_matlab_license():
    """Icepack Cloud Execution checkpoint: the MATLAB-license gate is
    ISSM-only. Icepack passes preflight regardless of the compute profile's
    license state -- true whether or not one happens to be configured."""
    assert cloud_run_preflight(model="icepack", matlab_license_configured=False) == []
    assert cloud_run_preflight(model="icepack", matlab_license_configured=True) == []
    assert_cloud_run_allowed(model="icepack", matlab_license_configured=False)  # no raise


def test_unknown_model_is_blocked():
    assert cloud_run_preflight(model="", matlab_license_configured=True)
    assert cloud_run_preflight(model="firedrake", matlab_license_configured=True)


def test_the_default_aws_compute_profile_has_no_license():
    """The AWS profile must stay unconfigured for MATLAB until a real cloud
    license mechanism exists -- so ISSM cloud is blocked by default."""
    from cryostack_src.resources.profiles import get_compute_profile

    aws = get_compute_profile("aws")
    assert aws.has_matlab_license is False
    assert aws.matlab_license_config() is None
    assert cloud_run_preflight(
        model="issm",
        matlab_license_configured=aws.has_matlab_license) != []
