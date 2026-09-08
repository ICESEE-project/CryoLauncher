# ============================================================
# Cloud backend (AWS CLI + AWS Batch)
# ============================================================
"""ICESEE's own AWS Batch submission contract (params.yaml + a
cloud_manifest.json uploaded to S3; ICESEE_S3_RUN / ICESEE_EXAMPLE /
ICESEE_RUN_SCRIPT env vars) -- unchanged. Credential handling and the
underlying AWS CLI invocation now delegate to
cryostack_src.cloud.legacy.aws_batch's AWSConfig/run_aws, the SAME
credential-stripping logic CryoLauncher's own AWSDriver.status/logs/
terminate use (kept in lockstep with cryostack_src.cloud.drivers.aws.auth
after a real bug there: DescribeJobs/Terminate once silently used ambient
host credentials instead of an assumed-role session). Before this, ICESEE's
own subprocess calls inherited the full ambient environment unconditionally
-- no BYO-AWS assumed-role credential ever had a way to reach them, and (had
one been wired in some other way) nothing would have stopped an ambient
AWS_* var from leaking through.

Every AWS-touching call takes an injectable ``aws`` callable
(``callable(AWSConfig, arguments) -> (code, out, err)``, default
``cryostack_src.cloud.legacy.aws_batch.run_aws``) so callers -- including
every test in this repo -- never need to touch a real ``aws`` binary.
"""

from __future__ import annotations

import re
import time
import json
from dataclasses import dataclass, field
from pathlib import Path

from cryostack_src.cloud.legacy.aws_batch import (
    AWSConfig as _SharedAWSConfig,
    run_aws as _shared_run_aws,
    terminate_batch_job as _shared_terminate_batch_job,
)

from .config_io import dump_yaml
from .example_discovery import find_run_script
from .local_runner import run_dir


@dataclass
class AWSBatchConfig:
    region: str = "us-east-1"
    profile: str | None = None
    #: assumed-role temporary credentials (BYO-AWS mode). When set they win
    #: over ``profile`` and ambient credentials are never consulted -- same
    #: rule as cryostack_src.cloud.drivers.aws.models.AWSConfig. Never
    #: persisted or logged.
    credentials: dict[str, str] | None = field(default=None, repr=False)
    s3_prefix: str = ""  # s3://bucket/prefix
    job_queue: str = ""
    job_definition: str = ""  # name[:revision]
    job_name: str = "icesee"

    def as_shared_config(self) -> _SharedAWSConfig:
        return _SharedAWSConfig(
            region=self.region, profile=self.profile, credentials=self.credentials,
        )


def _run(cfg: AWSBatchConfig, arguments: list[str], *, aws=None) -> tuple[int, str, str]:
    """Run one AWS CLI subcommand (no leading ``aws``/``--region``/
    ``--profile`` -- ``run_aws`` builds that prefix from ``cfg``)."""
    invoke = aws or _shared_run_aws
    return invoke(cfg.as_shared_config(), arguments)


def _parse_s3(s3_uri: str) -> tuple[str, str]:
    m = re.match(r"^s3://([^/]+)/(.*)$", s3_uri.rstrip("/"))
    if not m:
        raise ValueError("S3 path must look like: s3://bucket/prefix")
    return m.group(1), m.group(2)


def aws_test(cfg: AWSBatchConfig, *, aws=None) -> None:
    code, out, err = _run(cfg, ["sts", "get-caller-identity"], aws=aws)
    if code != 0:
        raise RuntimeError(err or out)


def aws_batch_submit(
    cfg: AWSBatchConfig,
    local_run_dir: Path,
    example_name: str,
    run_script_name: str,
    *,
    aws=None,
) -> dict:
    if not cfg.s3_prefix or not cfg.job_queue or not cfg.job_definition:
        raise ValueError("Cloud config missing: s3_prefix/job_queue/job_definition")

    run_id = time.strftime("%Y%m%d-%H%M%S")
    bucket, prefix = _parse_s3(cfg.s3_prefix)
    s3_run = f"s3://{bucket}/{prefix}/{run_id}"

    params_path = local_run_dir / "params.yaml"
    if not params_path.exists():
        raise FileNotFoundError(f"params.yaml not found: {params_path}")

    # upload params
    code, out, err = _run(
        cfg, ["s3", "cp", str(params_path), f"{s3_run}/params.yaml"], aws=aws,
    )
    if code != 0:
        raise RuntimeError(err or out)

    manifest = {"run_id": run_id, "example": example_name, "run_script": run_script_name}
    (local_run_dir / "cloud_manifest.json").write_text(json.dumps(manifest, indent=2))
    _run(
        cfg,
        ["s3", "cp", str(local_run_dir / "cloud_manifest.json"), f"{s3_run}/cloud_manifest.json"],
        aws=aws,
    )

    env = [
        {"name": "ICESEE_S3_RUN", "value": s3_run},
        {"name": "ICESEE_EXAMPLE", "value": example_name},
        {"name": "ICESEE_RUN_SCRIPT", "value": run_script_name},
    ]

    submit_args = [
        "batch",
        "submit-job",
        "--job-name",
        f"{cfg.job_name}-{run_id}",
        "--job-queue",
        cfg.job_queue,
        "--job-definition",
        cfg.job_definition,
        "--container-overrides",
        json.dumps({"environment": env}),
    ]
    code, out, err = _run(cfg, submit_args, aws=aws)
    if code != 0:
        raise RuntimeError(err or out)

    job_id = json.loads(out)["jobId"]
    return {"run_id": run_id, "batch_job_id": job_id, "s3_run": s3_run}


def aws_batch_status(cfg: AWSBatchConfig, job_id: str, *, aws=None) -> dict:
    code, out, err = _run(cfg, ["batch", "describe-jobs", "--jobs", job_id], aws=aws)
    if code != 0:
        raise RuntimeError(err or out)
    job = json.loads(out)["jobs"][0]
    return {"status": job.get("status", "?"), "reason": job.get("statusReason", "")}


def terminate_cloud_job(cfg: AWSBatchConfig, job_id: str) -> dict:
    """Cancel/terminate an AWS Batch job -- ICESEE had no terminate
    capability before this. Reuses CryoLauncher's own hardened
    terminate_batch_job (cancels if not yet started, terminates otherwise)
    against the same credential-aware config as everything else here.
    (terminate_batch_job has no injectable ``aws`` hook of its own -- tests
    patch ``cryostack_src.cloud.legacy.aws_batch.subprocess``, the same
    pattern the rest of this codebase's cloud tests already use.)"""
    return _shared_terminate_batch_job(cfg.as_shared_config(), job_id)


@dataclass
class CloudSubmitResult:
    success: bool
    run_dir: Path
    batch_job_id: str
    s3_run: str
    run_id: str
    messages: list[str]


def submit_cloud_example(
    *,
    example_name: str,
    example_cfg: dict,
    config: dict,
    region: str,
    profile: str | None,
    s3_prefix: str,
    job_queue: str,
    job_definition: str,
    job_name: str,
    credentials: dict[str, str] | None = None,
    run_dir_base: "Path | str | None" = None,
    run_dir_name: str | None = None,
    aws=None,
) -> CloudSubmitResult:
    rd = run_dir(run_dir_base, run_dir_name)
    dump_yaml(config, rd / "params.yaml")

    cfg = AWSBatchConfig(
        region=region or "us-east-1",
        profile=(profile or None),
        credentials=credentials,
        s3_prefix=s3_prefix,
        job_queue=job_queue,
        job_definition=job_definition,
        job_name=job_name or "icesee",
    )

    aws_test(cfg, aws=aws)
    resp = aws_batch_submit(cfg, rd, example_name, find_run_script(example_cfg).name, aws=aws)

    messages = [
        "[cloud] Submitted.",
        f"batch_job_id: {resp['batch_job_id']}",
        f"s3_run      : {resp['s3_run']}",
        "",
        "[batch image requirement]",
        "Your AWS Batch container must read ICESEE_S3_RUN and ICESEE_RUN_SCRIPT,",
        "download params.yaml from S3, run, then sync results back to S3.",
    ]

    return CloudSubmitResult(
        success=True,
        run_dir=rd,
        batch_job_id=resp["batch_job_id"],
        s3_run=resp["s3_run"],
        run_id=resp["run_id"],
        messages=messages,
    )
