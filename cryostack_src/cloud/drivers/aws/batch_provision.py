# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Batch Provisioning
# File        : batch_provision.py
#
# Description :
#     Idempotently provisions the AWS Batch on Fargate resources CryoStack
#     needs for cloud execution: a scale-to-zero compute environment, a job
#     queue, per-model job definitions and their CloudWatch log groups.
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
AWS Batch (Fargate) provisioning for CryoStack.

Every operation is **describe-before-create/update**:

* compute environment -> describe; create if absent; update if ``maxvCpus`` or
  the subnet / security-group set drifted;
* job queue           -> describe; create if absent; update if priority or the
  bound compute environment drifted;
* job definition      -> describe the active revisions; register a new revision
  only when the container spec / timeout / retry drifted;
* log group           -> create (tolerating "already exists") and pin retention.

Discovery stays in ``batch.py``; this module holds the resource-changing calls.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .auth import run_aws
from .batch import AWSBatchResources, discover_batch_resources
from .batch_config import (
    COMPUTE_ENVIRONMENT_NAME,
    DEFAULT_ISSM_JOB_CONFIG,
    DEFAULT_MAX_VCPUS,
    JOB_QUEUE_NAME,
    JOB_QUEUE_PRIORITY,
    LOG_RETENTION_DAYS,
    FargateJobConfig,
    compute_resources_payload,
    container_properties_payload,
    job_definition_fingerprint,
    job_definition_name,
    log_group_name,
)
from .models import AWSConfig


@dataclass
class AWSBatchProvisionResult:
    """Outcome of preparing CryoStack's AWS Batch resources."""

    resources: AWSBatchResources
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)
    log_groups: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    #: infrastructure state for the mirrored tested image (set by the driver);
    #: never a substitute for the scientific ``container`` provenance block.
    image_delivery: object | None = None
    #: same, for the Icepack tested-image delivery when requested
    #: (``include_icepack=True``); ``None`` when Icepack wasn't prepared.
    icepack_image_delivery: object | None = None
    #: same, for the ICESEE tested-image delivery when requested
    #: (``include_icesee=True``); ``None`` when ICESEE wasn't prepared.
    icesee_image_delivery: object | None = None


def _require_success(code: int, stdout: str, stderr: str, *, what: str) -> str:
    if code != 0:
        raise RuntimeError((stderr or stdout).strip() or f"{what} failed.")
    return stdout


# ── Batch resource readiness polling ─────────────────────────────────────
# AWS brings a compute environment / job queue to ``status == VALID``
# asynchronously after a create or update. Attaching a job queue to a
# still-transitioning compute environment fails with
#   "Compute Environment ... is not valid. It must be valid before attaching
#    it to the job queue."
# The fix is to poll ``describe-*`` until VALID -- never a fixed sleep.
BATCH_READY_INTERVAL_SECONDS = 10        # between describe-* polls
BATCH_READY_TIMEOUT_SECONDS = 300        # CE VALID is usually < 60s; queue < 30s


class BatchResourceNotReady(RuntimeError):
    """A Batch compute environment / job queue did not reach ``VALID``."""


def _poll_batch_status(
    describe: Callable[[], dict | None],
    *,
    what: str,
    interval: float = BATCH_READY_INTERVAL_SECONDS,
    timeout: float = BATCH_READY_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Poll ``describe()`` (returns the resource dict, or ``None`` if a lookup
    momentarily failed) until its ``status`` is ``VALID``.

    * ``VALID``   -> return the resource dict;
    * ``INVALID`` -> raise :class:`BatchResourceNotReady` with ``statusReason``;
    * deadline    -> raise with the last observed ``state`` / ``status`` /
      ``statusReason``.

    Deterministic for tests: the number of describe attempts is
    ``timeout // interval + 1`` and ``sleep`` is injectable.
    """
    attempts = max(1, int(timeout // max(1e-9, interval)) + 1)
    last: dict = {}
    for i in range(attempts):
        res = describe() or None
        if res:
            last = res
        status = (last.get("status") or "").upper()
        if status == "VALID":
            return last
        if status == "INVALID":
            raise BatchResourceNotReady(
                f"{what} is INVALID: "
                f"{last.get('statusReason') or 'no reason reported'}")
        if i < attempts - 1:
            sleep(interval)
    raise BatchResourceNotReady(
        f"{what} did not become VALID within ~{int(timeout)}s "
        f"(last state={last.get('state')!r} status={last.get('status')!r} "
        f"reason={last.get('statusReason') or 'none'})")


def _describe(config: AWSConfig, args: list[str]) -> dict:
    """A describe call whose non-zero exit means 'inspect failed', not
    'resource absent' -- callers pass a filter that simply returns [] when
    the named resource does not exist."""
    code, stdout, stderr = run_aws(config, args)
    _require_success(code, stdout, stderr, what=" ".join(args[:2]))
    return json.loads(stdout or "{}")


# ── CloudWatch log group ──────────────────────────────────────────────────
def ensure_log_group(config: AWSConfig, *, model: str) -> str:
    """Create ``/cryostack/batch/<model>`` (idempotent) and pin its retention.

    The ECS task execution role can write streams but not create the group, so
    CryoStack creates it up front rather than relying on ``awslogs-create-group``.
    """
    name = log_group_name(model)
    code, stdout, stderr = run_aws(
        config, ["logs", "create-log-group", "--log-group-name", name]
    )
    text = (stderr or stdout or "")
    if code != 0 and "ResourceAlreadyExistsException" not in text:
        raise RuntimeError(text.strip() or f"Unable to create log group {name}.")

    code, stdout, stderr = run_aws(
        config,
        [
            "logs", "put-retention-policy",
            "--log-group-name", name,
            "--retention-in-days", str(LOG_RETENTION_DAYS),
        ],
    )
    _require_success(code, stdout, stderr, what="logs put-retention-policy")
    return name


# ── compute environment ───────────────────────────────────────────────────
def _current_compute_environment(config: AWSConfig) -> dict | None:
    payload = _describe(
        config,
        ["batch", "describe-compute-environments",
         "--compute-environments", COMPUTE_ENVIRONMENT_NAME],
    )
    envs = payload.get("computeEnvironments", [])
    return envs[0] if envs else None


def ensure_compute_environment(
    config: AWSConfig,
    *,
    subnets: list[str],
    security_groups: list[str],
    max_vcpus: int = DEFAULT_MAX_VCPUS,
    ready_interval: float = BATCH_READY_INTERVAL_SECONDS,
    ready_timeout: float = BATCH_READY_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Return one of ``created`` / ``updated`` / ``reused``.

    In every case the compute environment is ``VALID`` before this returns --
    a fresh one is still transitioning right after ``create``, and a reused one
    may be mid-``UPDATING`` from an earlier aborted run. A queue cannot be
    attached to a non-``VALID`` compute environment.
    """
    what = f"compute environment {COMPUTE_ENVIRONMENT_NAME}"

    def _wait() -> None:
        _poll_batch_status(
            lambda: _current_compute_environment(config), what=what,
            interval=ready_interval, timeout=ready_timeout, sleep=sleep,
        )

    desired = compute_resources_payload(
        subnets=subnets, security_groups=security_groups, max_vcpus=max_vcpus,
    )
    current = _current_compute_environment(config)

    if current is None:
        code, stdout, stderr = run_aws(
            config,
            [
                "batch", "create-compute-environment",
                "--compute-environment-name", COMPUTE_ENVIRONMENT_NAME,
                "--type", "MANAGED",
                "--state", "ENABLED",
                "--compute-resources", json.dumps(desired),
            ],
        )
        _require_success(code, stdout, stderr, what="batch create-compute-environment")
        _wait()
        return "created"

    cr = current.get("computeResources") or {}
    drift = (
        int(cr.get("maxvCpus", -1)) != int(desired["maxvCpus"])
        or set(cr.get("subnets") or []) != set(desired["subnets"])
        or set(cr.get("securityGroupIds") or []) != set(desired.get("securityGroupIds") or [])
    )
    if not drift:
        if (current.get("status") or "").upper() != "VALID":
            _wait()                       # transitioning from a prior partial run
        return "reused"

    code, stdout, stderr = run_aws(
        config,
        [
            "batch", "update-compute-environment",
            "--compute-environment", COMPUTE_ENVIRONMENT_NAME,
            "--state", "ENABLED",
            "--compute-resources", json.dumps({
                "maxvCpus": desired["maxvCpus"],
                "subnets": desired["subnets"],
                **({"securityGroupIds": desired["securityGroupIds"]}
                   if desired.get("securityGroupIds") else {}),
            }),
        ],
    )
    _require_success(code, stdout, stderr, what="batch update-compute-environment")
    _wait()
    return "updated"


# ── job queue ─────────────────────────────────────────────────────────────
def _current_job_queue(config: AWSConfig) -> dict | None:
    payload = _describe(
        config,
        ["batch", "describe-job-queues", "--job-queues", JOB_QUEUE_NAME],
    )
    queues = payload.get("jobQueues", [])
    return queues[0] if queues else None


def _compute_env_in_order(order: list[dict]) -> set[str]:
    names: set[str] = set()
    for entry in order or []:
        ref = entry.get("computeEnvironment") or ""
        names.add(ref.rsplit("/", 1)[-1])          # accept ARN or bare name
    return names


def ensure_job_queue(
    config: AWSConfig,
    *,
    ready_interval: float = BATCH_READY_INTERVAL_SECONDS,
    ready_timeout: float = BATCH_READY_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Return one of ``created`` / ``updated`` / ``reused``.

    Requires the bound compute environment to be ``VALID`` first (AWS rejects a
    ``create-job-queue`` otherwise), and polls the queue itself to ``VALID``
    before returning.
    """
    what = f"job queue {JOB_QUEUE_NAME}"

    def _wait_queue() -> None:
        _poll_batch_status(
            lambda: _current_job_queue(config), what=what,
            interval=ready_interval, timeout=ready_timeout, sleep=sleep,
        )

    ce_order = [{"order": 1, "computeEnvironment": COMPUTE_ENVIRONMENT_NAME}]
    current = _current_job_queue(config)

    if current is None:
        # defensive: the CE must be VALID before it can be attached
        ce = _current_compute_environment(config)
        if (ce or {}).get("status", "").upper() != "VALID":
            _poll_batch_status(
                lambda: _current_compute_environment(config),
                what=f"compute environment {COMPUTE_ENVIRONMENT_NAME}",
                interval=ready_interval, timeout=ready_timeout, sleep=sleep,
            )
        code, stdout, stderr = run_aws(
            config,
            [
                "batch", "create-job-queue",
                "--job-queue-name", JOB_QUEUE_NAME,
                "--state", "ENABLED",
                "--priority", str(JOB_QUEUE_PRIORITY),
                "--compute-environment-order", json.dumps(ce_order),
            ],
        )
        _require_success(code, stdout, stderr, what="batch create-job-queue")
        _wait_queue()
        return "created"

    drift = (
        int(current.get("priority", -1)) != JOB_QUEUE_PRIORITY
        or COMPUTE_ENVIRONMENT_NAME not in _compute_env_in_order(
            current.get("computeEnvironmentOrder"))
        or (current.get("state") or "").upper() != "ENABLED"
    )
    if not drift:
        if (current.get("status") or "").upper() != "VALID":
            _wait_queue()
        return "reused"

    code, stdout, stderr = run_aws(
        config,
        [
            "batch", "update-job-queue",
            "--job-queue", JOB_QUEUE_NAME,
            "--state", "ENABLED",
            "--priority", str(JOB_QUEUE_PRIORITY),
            "--compute-environment-order", json.dumps(ce_order),
        ],
    )
    _require_success(code, stdout, stderr, what="batch update-job-queue")
    _wait_queue()
    return "updated"


# ── job definition ────────────────────────────────────────────────────────
def _active_job_definitions(config: AWSConfig, name: str) -> list[dict]:
    payload = _describe(
        config,
        ["batch", "describe-job-definitions",
         "--job-definition-name", name, "--status", "ACTIVE"],
    )
    return payload.get("jobDefinitions", [])


def ensure_job_definition(
    config: AWSConfig,
    *,
    model: str,
    image: str,
    job_role_arn: str,
    execution_role_arn: str,
    region: str,
    job_config: FargateJobConfig = DEFAULT_ISSM_JOB_CONFIG,
    command: list[str] | None = None,
    secrets: list[dict] | None = None,
) -> str:
    name = job_definition_name(model)
    desired_cp = container_properties_payload(
        model=model, image=image, job_role_arn=job_role_arn,
        execution_role_arn=execution_role_arn, region=region, config=job_config,
        command=command, secrets=secrets,
    )
    desired_fp = job_definition_fingerprint(
        container_properties=desired_cp,
        timeout_seconds=job_config.timeout_seconds,
        attempts=job_config.attempts,
    )

    for revision in sorted(
        _active_job_definitions(config, name),
        key=lambda r: int(r.get("revision", 0)), reverse=True,
    ):
        existing_fp = job_definition_fingerprint(
            container_properties=revision.get("containerProperties") or {},
            timeout_seconds=int(
                (revision.get("timeout") or {}).get("attemptDurationSeconds", 0)),
            attempts=int((revision.get("retryStrategy") or {}).get("attempts", 1)),
        )
        if existing_fp == desired_fp:
            return "reused"
        break  # only the latest revision matters

    code, stdout, stderr = run_aws(
        config,
        [
            "batch", "register-job-definition",
            "--job-definition-name", name,
            "--type", "container",
            "--platform-capabilities", "FARGATE",
            "--container-properties", json.dumps(desired_cp),
            "--timeout", json.dumps(
                {"attemptDurationSeconds": int(job_config.timeout_seconds)}),
            "--retry-strategy", json.dumps({"attempts": int(job_config.attempts)}),
        ],
    )
    _require_success(code, stdout, stderr, what="batch register-job-definition")
    return "created"


# ── orchestration ─────────────────────────────────────────────────────────
def ensure_batch_resources(
    config: AWSConfig,
    *,
    subnets: list[str],
    security_groups: list[str],
    job_role_arn: str,
    execution_role_arn: str,
    issm_image: str | None,
    max_vcpus: int = DEFAULT_MAX_VCPUS,
    issm_job_config: FargateJobConfig = DEFAULT_ISSM_JOB_CONFIG,
    job_command: list[str] | None = None,
    issm_secrets: list[dict] | None = None,
    include_icepack: bool = False,
    icepack_image: str | None = None,
    icepack_job_config: FargateJobConfig | None = None,
    include_icesee: bool = False,
    icesee_image: str | None = None,
    icesee_job_config: FargateJobConfig | None = None,
    icesee_command: list[str] | None = None,
    ready_interval: float = BATCH_READY_INTERVAL_SECONDS,
    ready_timeout: float = BATCH_READY_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> AWSBatchProvisionResult:
    """Prepare CryoStack's AWS Batch on Fargate environment, idempotently.

    The compute environment is waited to ``VALID`` before the queue is
    created/attached, and the queue is waited to ``VALID`` before the job
    definitions are registered. ``ready_interval`` / ``ready_timeout`` /
    ``sleep`` make the polling deterministic for tests.
    """
    result = AWSBatchProvisionResult(resources=None)  # type: ignore[arg-type]

    if not subnets:
        result.skipped.append("batch (no usable subnets discovered)")
        result.messages.append(
            "AWS Batch provisioning skipped: no subnets in the default VPC.")
        result.resources = discover_batch_resources(config)
        return result

    def _bucket(name: str, outcome: str) -> None:
        {"created": result.created, "updated": result.updated,
         "reused": result.reused}[outcome].append(name)

    _ready = dict(ready_interval=ready_interval, ready_timeout=ready_timeout,
                  sleep=sleep)

    # 1. compute environment (Fargate -- scale to zero); waited to VALID
    _bucket("compute_environment", ensure_compute_environment(
        config, subnets=subnets, security_groups=security_groups,
        max_vcpus=max_vcpus, **_ready,
    ))

    # 2. job queue -- only attached once the CE is VALID; waited to VALID
    _bucket("job_queue", ensure_job_queue(config, **_ready))

    # 3. per-model job definitions (+ their log groups)
    if job_role_arn and execution_role_arn and issm_image:
        result.log_groups.append(ensure_log_group(config, model="issm"))
        _bucket("issm_job_definition", ensure_job_definition(
            config, model="issm", image=issm_image, job_role_arn=job_role_arn,
            execution_role_arn=execution_role_arn, region=config.region,
            job_config=issm_job_config, command=job_command,
            secrets=issm_secrets,   # ISSM MATLAB license (Secrets Manager ARN)
        ))
    else:
        result.skipped.append(
            "issm_job_definition (needs job role, execution role and an image)")

    if include_icepack:
        if job_role_arn and execution_role_arn and icepack_image:
            result.log_groups.append(ensure_log_group(config, model="icepack"))
            _bucket("icepack_job_definition", ensure_job_definition(
                config, model="icepack", image=icepack_image, job_role_arn=job_role_arn,
                execution_role_arn=execution_role_arn, region=config.region,
                job_config=icepack_job_config or DEFAULT_ISSM_JOB_CONFIG,
                command=job_command,
            ))
        else:
            result.skipped.append(
                "icepack_job_definition (needs job role, execution role and an image)")

    if include_icesee:
        if job_role_arn and execution_role_arn and icesee_image:
            result.log_groups.append(ensure_log_group(config, model="icesee"))
            _bucket("icesee_job_definition", ensure_job_definition(
                config, model="icesee", image=icesee_image, job_role_arn=job_role_arn,
                execution_role_arn=execution_role_arn, region=config.region,
                job_config=icesee_job_config or DEFAULT_ISSM_JOB_CONFIG,
                # ICESEE is not one of cryostack_src.cloud.runtime's
                # SUPPORTED_CLOUD_MODELS and never shares the generic
                # `job_command` (CRYOSTACK_* env contract) ISSM/Icepack use --
                # it needs its own ICESEE_* env-var-driven command, passed in
                # by the caller (icesee_jupyter_book.core.cloud_runner's
                # icesee_batch_command()).
                command=icesee_command,
            ))
        else:
            result.skipped.append(
                "icesee_job_definition (needs job role, execution role and an image)")

    result.resources = discover_batch_resources(config)
    return result
