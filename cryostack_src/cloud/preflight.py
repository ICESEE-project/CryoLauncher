# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Cloud Run Preflight
# File        : preflight.py
#
# Description :
#     Gates that must pass before a billable cloud job is staged or submitted.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-31
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
Blocking checks for CryoStack cloud execution.

These run *before* anything is staged to S3 or submitted to Batch, so a
misconfigured run never becomes a billable job. The list is intentionally
small and provider-neutral.
"""

from __future__ import annotations

from .runtime import SUPPORTED_CLOUD_MODELS

_NO_MATLAB_LICENSE = (
    "[cloud][ERROR] ISSM cloud execution needs a MATLAB license reachable "
    "from AWS. The container image is ready, but ISSM runtime is not: add an "
    "AWS Secrets Manager secret (MLM_LICENSE_FILE value) in your AWS account "
    "and give CryoStack its ARN in Cloud Environment. The license value "
    "never leaves your account."
)


def cloud_run_preflight(*, model: str, matlab_license_configured: bool) -> list[str]:
    """Return the blocking reasons for a cloud run (empty list == clear to go).

    * unknown / unsupported model -> blocked (Icepack cloud is not ready);
    * ISSM without a configured cloud MATLAB license -> blocked. The license
      value itself is never handled here -- only whether one is configured.
    """
    reasons: list[str] = []
    m = (model or "").strip().lower()

    if m not in SUPPORTED_CLOUD_MODELS:
        reasons.append(
            f"[cloud][ERROR] model {model!r} has no supported cloud runtime yet."
        )
        return reasons

    if m == "issm" and not matlab_license_configured:
        reasons.append(_NO_MATLAB_LICENSE)

    return reasons


def assert_cloud_run_allowed(*, model: str, matlab_license_configured: bool) -> None:
    reasons = cloud_run_preflight(
        model=model, matlab_license_configured=matlab_license_configured)
    if reasons:
        from .runtime import CloudRuntimeError

        raise CloudRuntimeError(" ".join(reasons))
