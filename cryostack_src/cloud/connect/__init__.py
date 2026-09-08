# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Account Connection (Bring Your Own Account)
# File        : __init__.py
#
# Description :
#     End-user AWS account connection: a non-secret per-user connection
#     record, a cryptographically unique ExternalId, cross-account
#     STS AssumeRole, and a temporary-credential execution context.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-09-03
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
CryoStack "Bring your AWS account" connection layer.

A normal scientific user connects *their own* AWS account without ever
handing CryoStack a long-lived secret:

* CryoStack mints an :class:`AWSConnection` record -- ``connection_id``,
  ``external_id``, ``region``, and (after the user creates the role)
  ``role_arn`` + discovered ``account_id``. **No access keys, ever.**
* The user creates a cross-account IAM role that trusts the CryoStack
  principal to ``sts:AssumeRole`` *only* when ``sts:ExternalId`` equals the
  minted value.
* CryoStack calls :func:`assume_role`, receives *temporary* credentials, and
  wraps them in an :class:`AWSExecutionContext` that lives only for the
  operation -- never persisted, never logged, never placed in provenance.

Developer/operator mode (ambient AWS CLI credentials + optional profile)
is untouched; it remains the local-development and acceptance path.
"""

from __future__ import annotations

from .assume_role import (
    DEFAULT_SESSION_SECONDS,
    AssumeRoleError,
    assume_role,
)
from .cloudformation import (
    EXECUTION_ROLE_NAME,
    connection_stack_name,
    execution_role_template,
    quick_create_url,
    render_template,
)
from .context import AWSExecutionContext
from .defaults import CloudDefaults, default_runs_bucket, derive_cloud_defaults
from .execution import (
    MODE_BYO,
    MODE_DEVELOPER,
    CloudAccessError,
    CloudExecution,
    resolve_cloud_execution,
)
from .external_id import generate_external_id
from .models import AWSConnection, account_id_from_role_arn
from .onboarding import AWSOnboarding, OnboardingConfigError
from .principal import PrincipalNotConfiguredError, cryostack_principal_arn
from .redaction import assert_no_aws_secrets, redact_aws_secrets
from .store import AWSConnectionStore
from .verify import VerificationResult, verify_connection

__all__ = [
    "AWSConnection",
    "AWSConnectionStore",
    "AWSExecutionContext",
    "AWSOnboarding",
    "AssumeRoleError",
    "CloudAccessError",
    "CloudDefaults",
    "CloudExecution",
    "MODE_BYO",
    "MODE_DEVELOPER",
    "resolve_cloud_execution",
    "DEFAULT_SESSION_SECONDS",
    "EXECUTION_ROLE_NAME",
    "OnboardingConfigError",
    "PrincipalNotConfiguredError",
    "VerificationResult",
    "account_id_from_role_arn",
    "assert_no_aws_secrets",
    "assume_role",
    "connection_stack_name",
    "cryostack_principal_arn",
    "default_runs_bucket",
    "derive_cloud_defaults",
    "execution_role_template",
    "generate_external_id",
    "quick_create_url",
    "redact_aws_secrets",
    "render_template",
    "verify_connection",
]
