# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : ISSM MATLAB license (cloud runtime readiness)
# File        : matlab_license.py
#
# Description :
#     The configuration seam that makes ISSM CLOUD execution runnable.
#     "Container ready" (the ECR image exists) is NOT the same as
#     "ISSM runtime ready": ISSM drives a full MATLAB (R2024b) inside the
#     combined image, which checks out a network license at start. The image
#     ships NO license (deliberately -- v1.0.1 provenance), and a site
#     license server (e.g. a campus one) is not reachable from AWS
#     Fargate.
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""Resolve the ISSM cloud MATLAB-license readiness for a connected BYO-AWS
account -- **without ever handling the license value**.

Mechanism (AWS-native, BYO):

* the user creates an AWS Secrets Manager secret IN THEIR OWN ACCOUNT whose
  value is the ``MLM_LICENSE_FILE`` string (``<port>@<host>`` for a license
  server they can reach from the Batch compute environment's VPC, or a
  MathWorks online-licensing token);
* they give CryoStack only the secret's **ARN** (a non-secret identifier),
  stored on :class:`~cryostack_src.cloud.connect.models.AWSConnection`;
* Prepare Cloud registers the ISSM job definition with
  ``containerProperties.secrets = [{name: MLM_LICENSE_FILE, valueFrom: <arn>}]``
  and grants the Batch execution role ``secretsmanager:GetSecretValue`` on
  that ARN only (IAM -- outside this module);
* AWS Batch injects the value as an environment variable when the container
  starts. It is never in git, the image, an S3 run artifact, a manifest, a
  command preview, or a CryoStack log.

CryoStack's job here is only: given a connection, say whether ISSM cloud
runtime is configured, and hand the (non-secret) ARN to the provisioning
layer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: the container env var ISSM's MATLAB reads for its network license
MATLAB_LICENSE_ENV = "MLM_LICENSE_FILE"

#: arn:aws:secretsmanager:<region>:<account>:secret:<name>-<suffix>
_SECRET_ARN_RE = re.compile(
    r"\Aarn:aws:secretsmanager:[a-z0-9-]+:\d{12}:secret:[A-Za-z0-9/_+=.@-]+\Z"
)

#: substrings that would indicate a license VALUE (never an ARN) slipped in
_LICENSE_VALUE_HINTS = ("@", "mlm_license", "license_file", "lm_license")


@dataclass(frozen=True)
class CloudMatlabLicense:
    """Non-secret ISSM cloud-runtime license state for one connection."""

    configured: bool
    mechanism: str          # "secrets-manager" | "none"
    secret_arn: str         # "" unless mechanism == "secrets-manager"

    def as_public_dict(self) -> dict:
        return {
            "configured": self.configured,
            "mechanism": self.mechanism,
            "secret_arn": self.secret_arn,
        }

    def batch_secrets_block(self) -> list[dict]:
        """``containerProperties.secrets`` -- empty when unconfigured."""
        if not (self.configured and self.secret_arn):
            return []
        return [{"name": MATLAB_LICENSE_ENV, "valueFrom": self.secret_arn}]


NOT_CONFIGURED = CloudMatlabLicense(configured=False, mechanism="none", secret_arn="")


def is_secret_arn(value: str) -> bool:
    return bool(_SECRET_ARN_RE.match((value or "").strip()))


def assert_not_a_license_value(value: str) -> None:
    """Fail closed if what was handed in looks like a license VALUE rather
    than a Secrets Manager ARN (defence-in-depth: the value must never enter
    CryoStack)."""
    low = (value or "").strip().lower()
    if not low:
        return
    if low.startswith("arn:aws:secretsmanager:"):
        return
    if any(h in low for h in _LICENSE_VALUE_HINTS) or re.search(r"\d+@", low):
        raise ValueError(
            "Expected an AWS Secrets Manager secret ARN, not a MATLAB license "
            "value. The license value must stay in your AWS account and never "
            "be given to CryoStack."
        )


def resolve_cloud_matlab_license(connection) -> CloudMatlabLicense:
    """From an :class:`AWSConnection` (or anything with
    ``matlab_license_secret_arn``). Never raises for a plain missing value;
    an ARN-shaped string that is malformed is treated as unconfigured."""
    arn = (getattr(connection, "matlab_license_secret_arn", "") or "").strip()
    if arn and is_secret_arn(arn):
        return CloudMatlabLicense(configured=True, mechanism="secrets-manager",
                                  secret_arn=arn)
    return NOT_CONFIGURED
