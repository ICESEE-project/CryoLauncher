"""ICESEE Cloud execution adapter over the hardened CryoStack CloudBridge.

Step 1-3 of the staged migration in
``overnight/AUDIT_icesee_cloud_convergence.md``: introduce an adapter over
``CloudBridge`` (step 1), keep ICESEE's existing DA-workload
staging/submission contract behind it via an injected submitter (step 2),
and move status/terminate onto the REAL hardened ``AWSDriver`` lifecycle
(step 3) -- those two operations only need an already-submitted Batch
``job_id`` and never depended on how the job was submitted, so they get
CryoLauncher's own credential handling, error normalization, and
``ExecutionStatus`` shape for free, with zero change to the AWS-side job
definition or container image.

This module does NOT flatten ICESEE into a single-script CryoLauncher run:
the submitter still uploads ``params.yaml`` (the full DA identity --
forecast model, filter, ensemble size, observations, state/parameter
estimation, DA cycle) and the same ``ICESEE_S3_RUN`` / ``ICESEE_EXAMPLE`` /
``ICESEE_RUN_SCRIPT`` env vars the legacy path always has. Only the
lifecycle wrapper (credential handling, result/status normalization,
terminate) is shared with CryoLauncher.

No AWS is ever contacted directly by this module or its tests; every
AWS-touching call flows through an injectable ``aws`` callable all the way
down to :mod:`icesee_jupyter_book.core.cloud_runner`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cryostack_src.cloud.bridge import CloudBridge
from cryostack_src.execution.backend import ExecutionResult, ExecutionStatus

from .cloud_runner import submit_cloud_example


@dataclass(frozen=True)
class IceseeCloudBridgeConfig:
    """The account/session context one adapter call is scoped to. Build a
    fresh instance (and therefore a fresh :class:`CloudBridge`) per
    operation -- the same "temporary-role refresh per lifecycle operation"
    pattern CryoLauncher's own ``current_cloud_bridge()`` uses -- rather
    than caching one bridge across a session."""

    region: str
    profile: str | None = None
    #: assumed-role temporary credentials (BYO-AWS mode). Wins over
    #: ``profile``; never combined with it. Never persisted or logged.
    credentials: dict[str, str] | None = None
    #: injectable AWS transport for tests; ``None`` uses the real AWS CLI.
    aws: object = None

    def __post_init__(self):
        if not (self.region or "").strip():
            raise ValueError("An AWS region is required (no ambient default).")


def build_icesee_cloud_bridge(cfg: IceseeCloudBridgeConfig) -> CloudBridge:
    """A CloudBridge whose submit path is ICESEE's own upload/submit
    contract (unchanged), and whose status/terminate are the real
    CloudBackend/AWSDriver lifecycle."""

    def _icesee_submitter(**kwargs):
        return submit_cloud_example(
            region=cfg.region, profile=cfg.profile, credentials=cfg.credentials,
            aws=cfg.aws, **kwargs,
        )

    return CloudBridge(
        provider="aws",
        region=cfg.region,
        profile=cfg.profile,
        credentials=cfg.credentials,
        submitter=_icesee_submitter,
    )


def submit_icesee_cloud_run(
    bridge: CloudBridge,
    *,
    example_name: str,
    example_cfg: dict,
    config: dict,
    s3_prefix: str,
    job_queue: str,
    job_definition: str,
    job_name: str = "icesee",
    run_dir_base: "Path | str | None" = None,
    run_dir_name: str | None = None,
) -> ExecutionResult:
    """Submit an ICESEE DA run through the bridge. The local workspace
    directory (for the run_records.py manifest) is deterministic from
    ``run_dir_base``/``run_dir_name`` -- compute it the same way before
    calling this, exactly as the Local/Remote paths already do; it is not
    echoed back in ``ExecutionResult`` (CloudBackend's normalization only
    carries the S3-side identity, by design -- it is provider-neutral)."""
    return bridge.submit(
        example_name=example_name, example_cfg=example_cfg, config=config,
        s3_prefix=s3_prefix, job_queue=job_queue, job_definition=job_definition,
        job_name=job_name, run_dir_base=run_dir_base, run_dir_name=run_dir_name,
    )


def icesee_cloud_status(bridge: CloudBridge, *, job_id: str) -> ExecutionStatus:
    return bridge.status(job_id=job_id)


def icesee_cloud_terminate(bridge: CloudBridge, *, job_id: str) -> dict:
    return bridge.terminate(job_id=job_id)
