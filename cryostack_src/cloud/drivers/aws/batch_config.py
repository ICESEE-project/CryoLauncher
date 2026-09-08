# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Batch Configuration
# File        : batch_config.py
#
# Description :
#     Deterministic names and Fargate job specifications for CryoStack
#     AWS Batch execution. Definitions only -- no AWS calls.
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
AWS Batch resource configuration for CryoStack.

Kept separate from provisioning (``batch_provision.py``) and discovery
(``batch.py``) so the exact Fargate shape CryoStack asks AWS for is explicit,
reviewable and unit-testable without touching AWS.

First supported configuration: **AWS Batch on Fargate** -- managed, scale to
zero, no always-on EC2 capacity. Every job carries a mandatory timeout,
bounded vCPU/memory, bounded ephemeral storage and an ``awslogs`` driver.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── deterministic resource names ─────────────────────────────────────────────
# AWS Batch names are scoped to account + region, so (unlike the global S3
# bucket) they need no account suffix to stay deterministic.
COMPUTE_ENVIRONMENT_NAME = "cryostack-fargate"
JOB_QUEUE_NAME = "cryostack-queue"
JOB_DEFINITION_NAMES = {
    "issm": "cryostack-issm",
    "icepack": "cryostack-icepack",
    "icesee": "cryostack-icesee",
}
# ECR repositories that hold CryoStack's tested images (one per model). Kept
# here so provisioning, delivery and discovery agree on the name.
ECR_REPOSITORY_NAMES = {
    "issm": "cryostack-issm",
    "icepack": "cryostack-icepack",
    "icesee": "cryostack-icesee",
}

LOG_GROUP_PREFIX = "/cryostack/batch"
LOG_RETENTION_DAYS = 30                       # cost guardrail

# ── compute environment ─────────────────────────────────────────────────────
DEFAULT_MAX_VCPUS = 16                        # hard ceiling on concurrent vCPUs
JOB_QUEUE_PRIORITY = 1

# Valid AWS Fargate vCPU values and, for each, the [min, max] task memory (MiB)
# and the memory step. Used to reject an impossible task shape before AWS does.
_FARGATE_MEMORY_RULES: dict[str, tuple[int, int, int]] = {
    "0.25": (512, 2048, 512),
    "0.5": (1024, 4096, 1024),
    "1": (2048, 8192, 1024),
    "2": (4096, 16384, 1024),
    "4": (8192, 30720, 1024),
    "8": (16384, 61440, 4096),
    "16": (32768, 122880, 8192),
}

_MIN_EPHEMERAL_GIB = 21
_MAX_EPHEMERAL_GIB = 200
_MIN_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class FargateJobConfig:
    """The runtime shape of one CryoStack Batch job on Fargate."""

    vcpu: str = "2"
    memory_mib: str = "8192"                  # valid with vcpu="2"
    ephemeral_gib: int = 50                   # staged example tree + outputs/
    timeout_seconds: int = 3600              # mandatory -- a run is always bounded
    attempts: int = 1                        # never silently retry a billable job
    platform_version: str = "LATEST"
    assign_public_ip: str = "ENABLED"        # default-VPC public subnets -> ECR/S3
    cpu_architecture: str = "X86_64"
    operating_system_family: str = "LINUX"


DEFAULT_ISSM_JOB_CONFIG = FargateJobConfig()


def validate_fargate_job_config(config: FargateJobConfig) -> None:
    """Raise ``ValueError`` for a task shape AWS Fargate would reject."""
    rule = _FARGATE_MEMORY_RULES.get(str(config.vcpu))
    if rule is None:
        raise ValueError(
            f"Fargate vCPU must be one of {sorted(_FARGATE_MEMORY_RULES)}; "
            f"got {config.vcpu!r}"
        )
    lo, hi, step = rule
    try:
        memory = int(config.memory_mib)
    except (TypeError, ValueError):
        raise ValueError(f"memory_mib must be an integer MiB value; got {config.memory_mib!r}")
    if not (lo <= memory <= hi) or (memory - lo) % step:
        raise ValueError(
            f"Fargate memory {memory} MiB is not valid for {config.vcpu} vCPU "
            f"(allowed {lo}-{hi} MiB in steps of {step})"
        )
    if not (_MIN_EPHEMERAL_GIB <= int(config.ephemeral_gib) <= _MAX_EPHEMERAL_GIB):
        raise ValueError(
            f"ephemeral_gib must be {_MIN_EPHEMERAL_GIB}-{_MAX_EPHEMERAL_GIB}; "
            f"got {config.ephemeral_gib}"
        )
    if int(config.timeout_seconds) < _MIN_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout_seconds must be >= {_MIN_TIMEOUT_SECONDS}; got {config.timeout_seconds}"
        )
    if int(config.attempts) < 1:
        raise ValueError("attempts must be >= 1")


def log_group_name(model: str) -> str:
    return f"{LOG_GROUP_PREFIX}/{(model or 'run').strip().lower()}"


def job_definition_name(model: str) -> str:
    return JOB_DEFINITION_NAMES.get((model or "").strip().lower(), f"cryostack-{model}")


# ── payload builders (pure) ────────────────────────────────────────────────
def compute_resources_payload(
    *,
    subnets: list[str],
    security_groups: list[str],
    max_vcpus: int = DEFAULT_MAX_VCPUS,
) -> dict:
    """``computeResources`` for a Fargate (scale-to-zero) compute environment.

    No ``minvCpus``/``desiredvCpus`` and no instance types: Fargate provisions
    per-job and releases immediately, so nothing runs (or bills) while the
    queue is idle.
    """
    if not subnets:
        raise ValueError("a Fargate compute environment needs at least one subnet")
    if int(max_vcpus) < 1:
        raise ValueError("max_vcpus must be >= 1")
    payload: dict = {
        "type": "FARGATE",
        "maxvCpus": int(max_vcpus),
        "subnets": list(subnets),
    }
    if security_groups:
        payload["securityGroupIds"] = list(security_groups)
    return payload


def container_properties_payload(
    *,
    model: str,
    image: str,
    job_role_arn: str,
    execution_role_arn: str,
    region: str,
    config: FargateJobConfig = DEFAULT_ISSM_JOB_CONFIG,
    command: list[str] | None = None,
    secrets: list[dict] | None = None,
) -> dict:
    """``containerProperties`` for a Fargate CryoStack job definition.

    ``secrets`` (``[{"name","valueFrom"}]``) is passed straight through to
    ``containerProperties.secrets`` -- used for the ISSM MATLAB license
    (a Secrets Manager ARN in the user's own account; AWS Batch injects the
    value at launch). It is a list of ARN REFERENCES, never a value.
    """
    validate_fargate_job_config(config)
    if not image:
        raise ValueError("a job definition needs a container image reference")
    if not (job_role_arn and execution_role_arn):
        raise ValueError("job definition needs both a job role and an execution role")
    payload = {
        "image": image,
        # Commit 3 replaces this with the generic cloud runner entrypoint.
        "command": list(command or ["cryostack-run"]),
        "jobRoleArn": job_role_arn,
        "executionRoleArn": execution_role_arn,
        "resourceRequirements": [
            {"type": "VCPU", "value": str(config.vcpu)},
            {"type": "MEMORY", "value": str(config.memory_mib)},
        ],
        "networkConfiguration": {"assignPublicIp": config.assign_public_ip},
        "ephemeralStorage": {"sizeInGiB": int(config.ephemeral_gib)},
        "fargatePlatformConfiguration": {"platformVersion": config.platform_version},
        "runtimePlatform": {
            "cpuArchitecture": config.cpu_architecture,
            "operatingSystemFamily": config.operating_system_family,
        },
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": log_group_name(model),
                "awslogs-region": region,
                "awslogs-stream-prefix": (model or "run").strip().lower(),
            },
        },
    }
    clean_secrets = [
        {"name": str(s["name"]), "valueFrom": str(s["valueFrom"])}
        for s in (secrets or [])
        if isinstance(s, dict) and s.get("name") and s.get("valueFrom")
    ]
    if clean_secrets:
        # ARN references only -- fail closed if a raw value slipped through.
        for s in clean_secrets:
            if not s["valueFrom"].startswith("arn:aws:"):
                raise ValueError(
                    "containerProperties.secrets[].valueFrom must be an ARN, "
                    "never a value"
                )
        payload["secrets"] = clean_secrets
    return payload


def job_definition_fingerprint(
    *,
    container_properties: dict,
    timeout_seconds: int,
    attempts: int,
) -> dict:
    """The subset of a job definition CryoStack cares about, for
    describe-before-register drift detection."""
    cp = container_properties
    return {
        "image": cp.get("image"),
        "command": cp.get("command"),
        "jobRoleArn": cp.get("jobRoleArn"),
        "executionRoleArn": cp.get("executionRoleArn"),
        "resourceRequirements": sorted(
            (r.get("type"), r.get("value"))
            for r in cp.get("resourceRequirements", [])
        ),
        "assignPublicIp": (cp.get("networkConfiguration") or {}).get("assignPublicIp"),
        "ephemeralStorage": (cp.get("ephemeralStorage") or {}).get("sizeInGiB"),
        "platformVersion": (cp.get("fargatePlatformConfiguration") or {}).get("platformVersion"),
        "logDriver": (cp.get("logConfiguration") or {}).get("logDriver"),
        "logGroup": ((cp.get("logConfiguration") or {}).get("options") or {}).get("awslogs-group"),
        # secret ARN references only -- a change here (e.g. a MATLAB license
        # secret added/removed) re-registers the job definition
        "secrets": sorted(
            (s.get("name"), s.get("valueFrom")) for s in cp.get("secrets", [])
        ),
        "timeoutSeconds": int(timeout_seconds),
        "attempts": int(attempts),
    }
