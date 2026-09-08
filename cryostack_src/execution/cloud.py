# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Execution
# Component   : Cloud Backend
# File        : cloud.py
#
# Description :
#     Provides the CryoStack cloud execution abstraction while preserving
#     the existing AWS Batch implementation during the strangler migration.
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
CryoStack cloud execution backend.

This module provides the shared CryoStack execution interface for cloud
environments.

During the strangler migration, the backend wraps the existing AWS Batch
implementation in ``icesee_jupyter_book.core.cloud_runner`` rather than
replacing it.

The purpose of this layer is to allow CryoStack frontends to interact
with cloud execution through the same interface used for remote HPC
execution.
"""

from __future__ import annotations

from .backend import (
    ExecutionBackend,
    ExecutionResult,
    ExecutionStatus,
)

from cryostack_src.cloud.manager import CloudManager

class CloudBackend(
    ExecutionBackend
):
    """
    CryoStack cloud execution backend.

    The backend currently wraps the existing AWS Batch implementation.

    Cloud submission functions can be supplied dynamically so that ICESEE
    and CryoLauncher may initially continue using their existing submission
    implementations while sharing the same execution interface.
    """

    name = "cloud"

    def __init__(
        self,
        *,
        provider: str = "aws",
        region: str = "us-east-2",
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
        submitter=None,
    ) -> None:

        self.provider = provider
        self.region = region
        #: assumed-role temporary credentials (BYO-AWS mode); win over profile
        self.credentials = credentials
        self.profile = None if credentials else profile

        self._submitter = submitter

        self.manager = CloudManager()

    def submit(
        self,
        **kwargs,
    ) -> ExecutionResult:

        # A legacy submitter (old ICESEE params.yaml path) is still honoured
        # when injected; otherwise the driver's real submit path is used.
        result = self.manager.submit(
            provider=self.provider,
            region=self.region,
            profile=self.profile,
            credentials=self.credentials,
            submitter=self._submitter,
            **kwargs,
        )

        #
        # Existing cloud implementations may return
        # either dictionaries or dataclass objects.
        #
        extra: dict = {}
        if isinstance(
            result,
            dict,
        ):

            job_id = (
                result.get("batch_job_id")
                or result.get("job_id")
                or result.get("jobid")
            )

            s3_run = (
                result.get("s3_run")
                or result.get(
                    "working_directory"
                )
            )

            messages = result.get(
                "messages",
                [],
            )

            run_id = result.get(
                "run_id"
            )

            extra = {
                k: result[k]
                for k in (
                    "s3_input", "s3_outputs", "model", "run_target",
                    "job_queue", "job_definition",
                )
                if result.get(k)
            }

        else:

            job_id = (
                getattr(
                    result,
                    "batch_job_id",
                    None,
                )
                or getattr(
                    result,
                    "job_id",
                    None,
                )
                or getattr(
                    result,
                    "jobid",
                    None,
                )
            )

            s3_run = (
                getattr(
                    result,
                    "s3_run",
                    None,
                )
                or getattr(
                    result,
                    "working_directory",
                    None,
                )
            )

            messages = getattr(
                result,
                "messages",
                [],
            )

            run_id = getattr(
                result,
                "run_id",
                None,
            )

        return ExecutionResult(
            success=True,
            backend=self.name,
            job_id=(
                str(job_id)
                if job_id is not None
                else None
            ),
            working_directory=s3_run,
            output_directory=(
                f"{s3_run.rstrip('/')}/outputs"
                if s3_run
                else None
            ),
            log_path=None,
            metadata={
                "provider": "aws",
                "run_id": run_id,
                "s3_run": s3_run,
                **extra,
            },
            messages=list(
                messages or []
            ),
        )

    def status(
        self,
        *,
        job_id: str,
        region: str | None = None,
        profile: str | None = None,
        **kwargs,
    ) -> ExecutionStatus:
        result = self.manager.status(
            provider=self.provider,
            region=(
                region
                or self.region
            ),
            profile=(
                profile
                if profile is not None
                else self.profile
            ),
            credentials=self.credentials,
            job_id=job_id,
        )

        raw_state = (
            result.get("status")
            or ""
        ).strip()

        return ExecutionStatus(
            state=self._normalize_state(
                raw_state
            ),
            raw_state=raw_state,
            reason=(
                result.get("reason")
                or ""
            ),
            exit_code=result.get(
                "exit_code"
            ),
            metadata={
                "provider": "aws",
                "region": (
                    region
                    or self.region
                ),
                "log_stream": (
                    result.get(
                        "log_stream"
                    )
                ),
                "log_group": result.get("log_group"),
                "image": result.get("image"),
                "task_arn": result.get("task_arn"),
                "created_at": (
                    result.get(
                        "created_at"
                    )
                ),
                "started_at": (
                    result.get(
                        "started_at"
                    )
                ),
                "stopped_at": (
                    result.get(
                        "stopped_at"
                    )
                ),
                "job_queue": (
                    result.get(
                        "job_queue"
                    )
                ),
                "job_definition": (
                    result.get(
                        "job_definition"
                    )
                ),
            },
        )

    def logs(
        self,
        *,
        job_id: str,
        region: str | None = None,
        profile: str | None = None,
        **kwargs,
    ) -> str:

        return self.manager.logs(
            provider=self.provider,
            region=(
                region
                or self.region
            ),
            profile=(
                profile
                if profile is not None
                else self.profile
            ),
            credentials=self.credentials,
            job_id=job_id,
        )

    def terminate(
        self,
        *,
        job_id: str,
        region: str | None = None,
        profile: str | None = None,
        **kwargs,
    ):

        return self.manager.terminate(
            provider=self.provider,
            region=(
                region
                or self.region
            ),
            profile=(
                profile
                if profile is not None
                else self.profile
            ),
            credentials=self.credentials,
            job_id=job_id,
        )

    @staticmethod
    def _normalize_state(
        state: str,
    ) -> str:

        value = (
            state
            .strip()
            .upper()
        )

        if value in {
            "SUBMITTED",
            "PENDING",
            "RUNNABLE",
        }:
            return "queued"

        if value in {
            "STARTING",
            "RUNNING",
        }:
            return "running"

        if value == "SUCCEEDED":
            return "completed"

        if value == "FAILED":
            return "failed"

        return "unknown"
