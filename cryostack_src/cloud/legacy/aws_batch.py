# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Batch
# File        : aws_batch.py
#
# Description :
#     Provides low-level AWS Batch, CloudWatch Logs, and AWS CLI helpers
#     used by the CryoStack cloud execution backend.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-20
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
AWS Batch services for CryoStack.

This module contains AWS-specific execution primitives used by the
CryoStack cloud backend. It intentionally contains no frontend logic.

The functions here provide the cloud equivalents of common HPC
operations such as job status inspection, log retrieval, and job
termination.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field


@dataclass
class AWSConfig:
    """
    AWS connection configuration.

    Two credential sources are supported, and exactly one is used per call:

    * **developer / operator mode** -- ambient AWS CLI credentials, optionally
      selected by a named ``profile``;
    * **end-user assumed-role mode** -- ``credentials`` carries the temporary
      ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` / ``AWS_SESSION_TOKEN``
      from an ``sts:AssumeRole`` call. When present it wins and ``profile`` /
      ambient credentials are never consulted.

    This mirrors :class:`cryostack_src.cloud.drivers.aws.models.AWSConfig`
    exactly -- every caller in this codebase actually passes THAT class's
    instances through here (``AWSDriver.status/logs/terminate`` -> this
    module), never this bare dataclass; it is kept credential-shaped too so
    ``run_aws`` below is correct regardless of which one a caller constructs.
    """

    region: str = "us-east-2"
    profile: str | None = None
    credentials: dict[str, str] | None = field(default=None, repr=False)


#: env vars that carry an ambient credential source; dropped when an
#: assumed-role ``AWSConfig.credentials`` is supplied so the temporary
#: credentials are the only ones the CLI subprocess can see. Must stay in
#: lockstep with ``cryostack_src/cloud/drivers/aws/auth.py``'s ``run_aws``
#: -- that is the credentials-aware implementation ``submit_batch_job`` uses;
#: this module is the one ``AWSDriver.status/logs/terminate`` call, and
#: previously did NOT read ``config.credentials`` at all (subprocess.run with
#: no ``env=`` override, i.e. plain ambient-environment passthrough) -- the
#: exact reason DescribeJobs/Terminate reached AWS as the host's own ambient
#: identity while SubmitJob correctly used the assumed-role session.
_AMBIENT_CRED_ENV = (
    "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN",
)


def aws_command(
    config: AWSConfig,
) -> list[str]:
    """
    Build the base AWS CLI command.
    """

    command = ["aws"]

    # assumed-role temporary credentials win and never combine with a profile
    # (matches drivers/aws/auth.py's aws_command exactly)
    if config.profile and not getattr(config, "credentials", None):
        command.extend([
            "--profile",
            config.profile,
        ])

    if config.region:
        command.extend([
            "--region",
            config.region,
        ])

    return command


def run_aws(
    config: AWSConfig,
    arguments: list[str],
) -> tuple[int, str, str]:
    """
    Execute an AWS CLI command.

    When ``config.credentials`` carries assumed-role temporary credentials,
    the subprocess environment is the current environment with every ambient
    AWS credential var stripped and only the temporary
    ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` / ``AWS_SESSION_TOKEN``
    triple set -- the CLI cannot fall back to a host profile or ambient
    identity. Developer mode (no ``credentials``) is unchanged: ``env=None``
    inherits the current process environment exactly as before.
    """

    credentials = getattr(config, "credentials", None)
    env = None
    if credentials:
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in _AMBIENT_CRED_ENV
        }
        # only the three standard STS env vars are honoured
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            if credentials.get(key):
                env[key] = credentials[key]

    process = subprocess.run(
        aws_command(config) + arguments,
        capture_output=True,
        text=True,
        env=env,
    )

    return (
        process.returncode,
        process.stdout,
        process.stderr,
    )


def require_success(
    code: int,
    stdout: str,
    stderr: str,
) -> str:
    """
    Raise an exception when an AWS CLI operation fails.
    """

    if code != 0:
        raise RuntimeError(
            (stderr or stdout).strip()
            or "AWS command failed."
        )

    return stdout


def describe_job(
    config: AWSConfig,
    job_id: str,
) -> dict:
    """
    Return the complete AWS Batch job description.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "batch",
            "describe-jobs",
            "--jobs",
            job_id,
        ],
    )

    require_success(
        code,
        stdout,
        stderr,
    )

    payload = json.loads(
        stdout or "{}"
    )

    jobs = payload.get(
        "jobs",
        [],
    )

    if not jobs:
        raise RuntimeError(
            f"AWS Batch job not found: {job_id}"
        )

    return jobs[0]


def batch_status(
    config: AWSConfig,
    job_id: str,
) -> dict:
    """
    Return normalized information from an AWS Batch job.
    """

    job = describe_job(
        config,
        job_id,
    )

    container = (
        job.get("container")
        or {}
    )

    return {
        "status": job.get(
            "status",
            "",
        ),
        "reason": (
            job.get("statusReason")
            or container.get("reason")
            or ""
        ),
        "exit_code": container.get(
            "exitCode"
        ),
        "log_stream": container.get(
            "logStreamName"
        ),
        # non-secret resource identity revealed incrementally by DescribeJobs
        # (used to build the AWS diagnostics menu -- never a credential)
        "log_group": (
            (container.get("logConfiguration") or {})
            .get("options", {})
            .get("awslogs-group")
        ),
        "image": container.get("image"),
        "task_arn": container.get("taskArn"),
        "created_at": job.get(
            "createdAt"
        ),
        "started_at": job.get(
            "startedAt"
        ),
        "stopped_at": job.get(
            "stoppedAt"
        ),
        "job_name": job.get(
            "jobName"
        ),
        "job_queue": job.get(
            "jobQueue"
        ),
        "job_definition": job.get(
            "jobDefinition"
        ),
    }


def batch_logs(
    config: AWSConfig,
    job_id: str,
    *,
    limit: int = 200,
    log_group: str = "/aws/batch/job",
) -> str:
    """
    Retrieve recent CloudWatch logs for an AWS Batch job.
    """

    job = describe_job(
        config,
        job_id,
    )

    container = (
        job.get("container")
        or {}
    )

    log_stream = container.get(
        "logStreamName"
    )

    if not log_stream:
        status = job.get(
            "status",
            "UNKNOWN",
        )

        return (
            "CloudWatch log stream is not "
            f"available yet. Job status: {status}"
        )

    code, stdout, stderr = run_aws(
        config,
        [
            "logs",
            "get-log-events",
            "--log-group-name",
            log_group,
            "--log-stream-name",
            log_stream,
            "--limit",
            str(max(1, int(limit))),
            "--no-start-from-head",
        ],
    )

    require_success(
        code,
        stdout,
        stderr,
    )

    payload = json.loads(
        stdout or "{}"
    )

    events = payload.get(
        "events",
        [],
    )

    if not events:
        return "(no CloudWatch log output yet)"

    return "\n".join(
        str(
            event.get(
                "message",
                "",
            )
        )
        for event in events
    )


def terminate_batch_job(
    config: AWSConfig,
    job_id: str,
    *,
    reason: str = (
        "Terminated from CryoStack"
    ),
) -> dict:
    """
    Cancel or terminate an AWS Batch job depending on its state.

    Jobs that have not started are cancelled. Jobs that have started
    are terminated.
    """

    job = describe_job(
        config,
        job_id,
    )

    status = (
        job.get("status")
        or ""
    ).upper()

    if status in {
        "SUCCEEDED",
        "FAILED",
    }:
        return {
            "ok": True,
            "action": "none",
            "status": status,
            "message": (
                "Job has already finished."
            ),
        }

    if status in {
        "SUBMITTED",
        "PENDING",
        "RUNNABLE",
    }:
        operation = "cancel-job"
        action = "cancelled"

    else:
        operation = "terminate-job"
        action = "terminated"

    code, stdout, stderr = run_aws(
        config,
        [
            "batch",
            operation,
            "--job-id",
            job_id,
            "--reason",
            reason,
        ],
    )

    require_success(
        code,
        stdout,
        stderr,
    )

    return {
        "ok": True,
        "action": action,
        "status": status,
        "job_id": job_id,
    }

def has_credentials(
    config: AWSConfig,
) -> bool:
    """
    Return whether AWS CLI credentials are available.
    """

    code, _, _ = run_aws(
        config,
        [
            "sts",
            "get-caller-identity",
        ],
    )

    return code == 0