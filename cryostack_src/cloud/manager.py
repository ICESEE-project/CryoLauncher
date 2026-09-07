# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Cloud Manager
# File        : manager.py
#
# Description :
#     Resolves cloud-provider drivers and exposes a provider-independent
#     interface for cloud discovery, provisioning, and job lifecycle
#     operations.
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
High-level CryoStack cloud manager.

CloudManager is the public cloud API used by execution backends and
frontends. Provider-specific behavior remains inside cloud drivers.

Credential source (mutually exclusive, resolved per call):

* ``profile`` / ambient  -- developer / operator mode;
* ``credentials``        -- end-user assumed-role mode: the temporary
  ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` / ``AWS_SESSION_TOKEN``
  triple from :func:`cryostack_src.cloud.connect.assume_role`. It is passed
  straight through to the driver and never stored or logged here.
"""

from __future__ import annotations

from .drivers import (
    AWSDriver,
    CloudDriver,
)


class CloudManager:
    """
    Provider-independent CryoStack cloud manager.
    """

    def driver(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
        submitter=None,
    ) -> CloudDriver:

        provider_name = (
            provider
            .strip()
            .lower()
        )

        if provider_name == "aws":

            return AWSDriver(
                region=region,
                profile=profile,
                credentials=credentials,
                submitter=submitter,
            )

        raise ValueError(
            f"Unsupported cloud provider: {provider}"
        )

    # ---------------------------------------------------------
    # Discovery / provisioning
    # ---------------------------------------------------------

    def account(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
            credentials=credentials,
        ).account()

    def capabilities(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
            credentials=credentials,
        ).capabilities()

    def prepare_storage(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
        bucket: str | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
            credentials=credentials,
        ).prepare_storage(
            bucket=bucket,
        )

    def network(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
            credentials=credentials,
        ).network()

    def iam(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
            credentials=credentials,
        ).iam()

    def registry(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
            credentials=credentials,
        ).registry()

    def batch(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
            credentials=credentials,
        ).batch()

    def bootstrap(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
        bucket: str | None = None,
        matlab_secret_arn: str = "",
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
            credentials=credentials,
        ).bootstrap(
            bucket=bucket,
            matlab_secret_arn=matlab_secret_arn,
        )

    def prepare_batch(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
        include_icepack: bool = False,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
            credentials=credentials,
        ).prepare_batch(
            include_icepack=include_icepack,
        )

    # ---------------------------------------------------------
    # Runtime lifecycle
    # ---------------------------------------------------------

    def submit(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
        submitter=None,
        **kwargs,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
            credentials=credentials,
            submitter=submitter,
        ).submit(
            **kwargs
        )

    def status(
        self,
        *,
        provider: str,
        region: str,
        job_id: str,
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
            credentials=credentials,
        ).status(
            job_id
        )

    def logs(
        self,
        *,
        provider: str,
        region: str,
        job_id: str,
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
            credentials=credentials,
        ).logs(
            job_id
        )

    def terminate(
        self,
        *,
        provider: str,
        region: str,
        job_id: str,
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
    ):

        return self.driver(
            provider=provider,
            region=region,
            profile=profile,
            credentials=credentials,
        ).terminate(
            job_id
        )
