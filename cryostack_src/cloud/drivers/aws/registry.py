# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Registry
# File        : registry.py
#
# Description :
#     Discovers and manages Amazon ECR repositories used by CryoStack
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
AWS container registry services for CryoStack.

This module provides Amazon ECR discovery helpers used by CryoStack
cloud execution.

For now the implementation is discovery-oriented. Repository creation,
cross-account access, and image publishing will be added once the
official CryoStack image distribution model is finalized.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .auth import run_aws
from .models import AWSConfig


@dataclass
class AWSRegistryResources:
    """
    ECR resources discovered for CryoStack.
    """

    repositories: list[dict]

    issm_repository: str | None = None
    icepack_repository: str | None = None
    icesee_repository: str | None = None

    issm_repository_uri: str | None = None
    icepack_repository_uri: str | None = None
    icesee_repository_uri: str | None = None

    missing: list[str] | None = None


def _require_success(
    code: int,
    stdout: str,
    stderr: str,
) -> str:
    """
    Raise when an ECR operation fails.
    """

    if code != 0:
        raise RuntimeError(
            (stderr or stdout).strip()
            or "AWS ECR command failed."
        )

    return stdout


def list_repositories(
    config: AWSConfig,
) -> list[dict]:
    """
    Return ECR repositories visible in the configured region.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "ecr",
            "describe-repositories",
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

    return payload.get(
        "repositories",
        [],
    )


def find_repository(
    repositories: list[dict],
    names: list[str],
) -> dict | None:
    """
    Find the first ECR repository matching one of the supplied names.
    """

    wanted = {
        name.strip().lower()
        for name in names
    }

    for repository in repositories:

        name = (
            repository.get(
                "repositoryName"
            )
            or ""
        )

        if (
            name.strip().lower()
            in wanted
        ):
            return repository

    return None


def discover_registry_resources(
    config: AWSConfig,
) -> AWSRegistryResources:
    """
    Discover ECR repositories that may contain CryoStack model images.
    """

    repositories = list_repositories(
        config
    )

    issm = find_repository(
        repositories,
        [
            "cryostack-issm",
            "icesee-issm",
            "issm",
        ],
    )

    icepack = find_repository(
        repositories,
        [
            "cryostack-icepack",
            "icesee-icepack",
            "icepack",
        ],
    )

    icesee = find_repository(
        repositories,
        [
            "cryostack-icesee",
            "icesee",
        ],
    )

    missing: list[str] = []

    if not issm:
        missing.append(
            "issm_repository"
        )

    if not icepack:
        missing.append(
            "icepack_repository"
        )

    if not icesee:
        missing.append(
            "icesee_repository"
        )

    return AWSRegistryResources(
        repositories=repositories,
        issm_repository=(
            issm.get(
                "repositoryName"
            )
            if issm
            else None
        ),
        icepack_repository=(
            icepack.get(
                "repositoryName"
            )
            if icepack
            else None
        ),
        icesee_repository=(
            icesee.get(
                "repositoryName"
            )
            if icesee
            else None
        ),
        issm_repository_uri=(
            issm.get(
                "repositoryUri"
            )
            if issm
            else None
        ),
        icepack_repository_uri=(
            icepack.get(
                "repositoryUri"
            )
            if icepack
            else None
        ),
        icesee_repository_uri=(
            icesee.get(
                "repositoryUri"
            )
            if icesee
            else None
        ),
        missing=missing,
    )