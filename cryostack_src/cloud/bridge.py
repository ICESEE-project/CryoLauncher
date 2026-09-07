from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cryostack_src.execution.backend import ExecutionResult, ExecutionStatus
from cryostack_src.execution.cloud import CloudBackend

from .manager import CloudManager


class CloudBridge:
    """Stable, presentation-neutral API for CryoLauncher cloud operations."""

    def __init__(
        self,
        *,
        provider: str = "aws",
        region: str = "us-east-2",
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
        submitter: Callable[..., Any] | None = None,
        results_sync: Callable[..., Any] | None = None,
    ) -> None:
        self.provider = provider
        self.region = region
        #: assumed-role temporary credentials (BYO-AWS mode). When set they
        #: win over ``profile`` and no ambient credentials are consulted.
        self.credentials = credentials
        self.profile = None if credentials else profile
        self.submitter = submitter
        self.results_sync = results_sync
        self.backend = CloudBackend(
            provider=provider,
            region=region,
            profile=self.profile,
            credentials=credentials,
            submitter=submitter,
        )
        self.manager = CloudManager()

    def submit(self, **kwargs) -> ExecutionResult:
        """Submit a staged cloud run.

        A legacy ``submitter`` (old ICESEE ``params.yaml`` path) still wins when
        one was injected. Otherwise the run goes through the real path:
        preflight -> S3 staging -> ``aws batch submit-job`` inside
        :class:`AWSDriver.submit`.
        """
        kwargs.pop("display_region", None)
        # drop presentation-only kwargs the driver does not use
        kwargs.pop("backend", None)
        return self.backend.submit(**kwargs)

    def status(self, *, job_id: str) -> ExecutionStatus:
        return self.backend.status(job_id=job_id)

    def logs(self, *, job_id: str) -> str:
        return self.backend.logs(job_id=job_id)

    def terminate(self, *, job_id: str):
        return self.backend.terminate(job_id=job_id)

    def results(self, *, s3_uri: str, **kwargs):
        if self.results_sync is None:
            raise RuntimeError("Cloud result synchronization is not configured.")
        return self.results_sync(
            s3_uri=s3_uri,
            region=kwargs.pop("region", self.region),
            profile=kwargs.pop("profile", self.profile),
            credentials=kwargs.pop("credentials", self.credentials),
            **kwargs,
        )

    def check_environment(self):
        return self.manager.capabilities(
            provider=self.provider,
            region=self.region,
            profile=self.profile,
            credentials=self.credentials,
        )

    def prepare_environment(self, *, bucket: str | None = None,
                            matlab_secret_arn: str = ""):
        return self.manager.bootstrap(
            provider=self.provider,
            region=self.region,
            profile=self.profile,
            credentials=self.credentials,
            bucket=bucket,
            matlab_secret_arn=matlab_secret_arn,
        )
