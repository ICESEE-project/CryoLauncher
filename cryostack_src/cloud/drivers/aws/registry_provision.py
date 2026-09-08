# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Registry Provisioning
# File        : registry_provision.py
#
# Description :
#     Creates and prepares Amazon ECR repositories used by CryoStack
#     container-based cloud execution environments.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-24
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
AWS ECR provisioning services for CryoStack.

This module creates the ECR repositories required for CryoStack cloud
execution. Repository discovery remains in ``registry.py`` while this
module contains resource-changing operations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .auth import run_aws
from .batch_config import ECR_REPOSITORY_NAMES
from .models import AWSConfig
from .registry import (
    AWSRegistryResources,
    discover_registry_resources,
)


@dataclass
class AWSRegistryProvisionResult:
    """
    Result of preparing CryoStack ECR repositories.
    """

    resources: AWSRegistryResources

    created: list[str]
    reused: list[str]


def _require_success(
    code: int,
    stdout: str,
    stderr: str,
) -> str:
    """
    Raise when an ECR provisioning operation fails.
    """

    if code != 0:
        raise RuntimeError(
            (stderr or stdout).strip()
            or "AWS ECR provisioning failed."
        )

    return stdout


def create_repository(
    config: AWSConfig,
    *,
    repository_name: str,
) -> dict:
    """
    Create an ECR repository.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "ecr",
            "create-repository",
            "--repository-name",
            repository_name,
            "--image-scanning-configuration",
            "scanOnPush=true",
            "--image-tag-mutability",
            "MUTABLE",
        ],
    )

    _require_success(
        code,
        stdout,
        stderr,
    )

    payload = json.loads(
        stdout or "{}"
    )

    repository = payload.get(
        "repository",
        {},
    )

    if not repository:
        raise RuntimeError(
            "AWS did not return the created ECR repository."
        )

    return repository


def ensure_repository(
    config: AWSConfig,
    *,
    repository_name: str,
) -> tuple[dict, bool]:
    """
    Ensure an ECR repository exists.

    Returns the repository metadata and whether it was created.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "ecr",
            "describe-repositories",
            "--repository-names",
            repository_name,
        ],
    )

    if code == 0:

        payload = json.loads(
            stdout or "{}"
        )

        repositories = payload.get(
            "repositories",
            [],
        )

        if repositories:
            return (
                repositories[0],
                False,
            )

    error_text = (
        stderr
        or stdout
        or ""
    )

    if (
        code != 0
        and "RepositoryNotFoundException"
        not in error_text
    ):
        raise RuntimeError(
            error_text.strip()
            or (
                "Unable to inspect ECR repository "
                f"{repository_name}."
            )
        )

    repository = create_repository(
        config,
        repository_name=repository_name,
    )

    return (
        repository,
        True,
    )


def ensure_registry_resources(
    config: AWSConfig,
    *,
    include_icepack: bool = False,
    include_icesee: bool = False,
) -> AWSRegistryProvisionResult:
    """
    Ensure CryoStack model repositories exist in ECR.

    ISSM is currently required for cloud parity. Icepack and ICESEE can
    each be provisioned at the same time when requested.
    """

    created: list[str] = []
    reused: list[str] = []

    required = [
        ECR_REPOSITORY_NAMES["issm"],
    ]

    if include_icepack:
        required.append(
            ECR_REPOSITORY_NAMES["icepack"]
        )

    if include_icesee:
        required.append(
            ECR_REPOSITORY_NAMES["icesee"]
        )

    for repository_name in required:

        _, was_created = ensure_repository(
            config,
            repository_name=repository_name,
        )

        if was_created:
            created.append(
                repository_name
            )

        else:
            reused.append(
                repository_name
            )

    resources = discover_registry_resources(
        config
    )

    return AWSRegistryProvisionResult(
        resources=resources,
        created=created,
        reused=reused,
    )