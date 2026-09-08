# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Batch
# File        : batch.py
#
# Description :
#     Discovers AWS Batch compute environments, job queues, and job
#     definitions available for CryoStack cloud execution.
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
AWS Batch discovery services for CryoStack.

This module discovers existing AWS Batch resources that may be reused
by CryoStack.

The current implementation is intentionally read-only. Resource
provisioning will be added after capability discovery and IAM/network
requirements have been validated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .auth import run_aws
from .batch_config import (
    COMPUTE_ENVIRONMENT_NAME,
    JOB_DEFINITION_NAMES,
    JOB_QUEUE_NAME,
)
from .models import AWSConfig


@dataclass
class AWSBatchResources:
    """
    AWS Batch resources discovered for CryoStack.
    """

    compute_environments: list[dict]
    job_queues: list[dict]
    job_definitions: list[dict]

    compute_environment: str | None = None
    job_queue: str | None = None

    issm_job_definition: str | None = None
    icepack_job_definition: str | None = None
    icesee_job_definition: str | None = None

    missing: list[str] | None = None


def _require_success(
    code: int,
    stdout: str,
    stderr: str,
) -> str:
    """
    Raise when an AWS Batch discovery operation fails.
    """

    if code != 0:
        raise RuntimeError(
            (stderr or stdout).strip()
            or "AWS Batch command failed."
        )

    return stdout


def list_compute_environments(
    config: AWSConfig,
) -> list[dict]:
    """
    Return AWS Batch compute environments in the configured region.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "batch",
            "describe-compute-environments",
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
        "computeEnvironments",
        [],
    )


def list_job_queues(
    config: AWSConfig,
) -> list[dict]:
    """
    Return AWS Batch job queues in the configured region.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "batch",
            "describe-job-queues",
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
        "jobQueues",
        [],
    )


def list_job_definitions(
    config: AWSConfig,
) -> list[dict]:
    """
    Return active AWS Batch job definitions.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "batch",
            "describe-job-definitions",
            "--status",
            "ACTIVE",
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
        "jobDefinitions",
        [],
    )


def _find_named_resource(
    resources: list[dict],
    *,
    field: str,
    names: list[str],
) -> dict | None:
    """
    Find the first AWS resource matching one of the supplied names.
    """

    wanted = {
        name.strip().lower()
        for name in names
    }

    for resource in resources:

        value = (
            resource.get(field)
            or ""
        )

        if value.strip().lower() in wanted:
            return resource

    return None


def discover_batch_resources(
    config: AWSConfig,
) -> AWSBatchResources:
    """
    Discover AWS Batch resources that CryoStack may reuse.
    """

    compute_environments = (
        list_compute_environments(
            config
        )
    )

    job_queues = list_job_queues(
        config
    )

    job_definitions = (
        list_job_definitions(
            config
        )
    )

    compute = _find_named_resource(
        compute_environments,
        field="computeEnvironmentName",
        names=[
            COMPUTE_ENVIRONMENT_NAME,
            "cryostack-compute",
            "icesee-compute",
            "cryostack-batch-compute",
        ],
    )

    queue = _find_named_resource(
        job_queues,
        field="jobQueueName",
        names=[
            JOB_QUEUE_NAME,
            "icesee-queue",
            "cryostack-batch-queue",
        ],
    )

    issm_definition = _find_named_resource(
        job_definitions,
        field="jobDefinitionName",
        names=[
            JOB_DEFINITION_NAMES["issm"],
            "icesee-issm",
            "issm",
        ],
    )

    icepack_definition = _find_named_resource(
        job_definitions,
        field="jobDefinitionName",
        names=[
            JOB_DEFINITION_NAMES["icepack"],
            "icesee-icepack",
            "icepack",
        ],
    )

    icesee_definition = _find_named_resource(
        job_definitions,
        field="jobDefinitionName",
        names=[
            JOB_DEFINITION_NAMES["icesee"],
            "icesee",
        ],
    )

    missing: list[str] = []

    if not compute:
        missing.append(
            "compute_environment"
        )

    if not queue:
        missing.append(
            "job_queue"
        )

    if not issm_definition:
        missing.append(
            "issm_job_definition"
        )

    if not icepack_definition:
        missing.append(
            "icepack_job_definition"
        )

    if not icesee_definition:
        missing.append(
            "icesee_job_definition"
        )

    return AWSBatchResources(
        compute_environments=(
            compute_environments
        ),
        job_queues=job_queues,
        job_definitions=job_definitions,
        compute_environment=(
            compute.get(
                "computeEnvironmentName"
            )
            if compute
            else None
        ),
        job_queue=(
            queue.get(
                "jobQueueName"
            )
            if queue
            else None
        ),
        issm_job_definition=(
            issm_definition.get(
                "jobDefinitionName"
            )
            if issm_definition
            else None
        ),
        icepack_job_definition=(
            icepack_definition.get(
                "jobDefinitionName"
            )
            if icepack_definition
            else None
        ),
        missing=missing,
    )