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


#: AWS Fargate's own vCPU ceiling for a single Batch task
#: (cryostack_src/cloud/drivers/aws/batch_config.py::DEFAULT_MAX_VCPUS /
#: _FARGATE_MEMORY_RULES, which stops at "16"). ICESEE's real parallel
#: contract (icesee_jupyter_book/core/remote_runner.py's SLURM template) is
#: a single `mpirun -np NP ...` launch -- one co-located process group, not
#: a multi-node topology -- so it maps correctly onto ONE Fargate task for
#: any NP within this ceiling. Beyond it, Fargate cannot run a multi-node/
#: co-scheduled MPI job at all; that is a genuine infrastructure limit, not
#: something this function works around.
MAX_SINGLE_TASK_MPI_RANKS = 16


def build_icesee_container_env(
    *,
    s3_run: str,
    example_name: str,
    run_script_name: str,
    np: int | None = None,
    nens: int | None = None,
    model_nprocs: int | None = None,
) -> list[dict]:
    """The AWS Batch ``containerOverrides.environment`` list for an ICESEE
    cloud run -- the same three identity env vars as before
    (``ICESEE_S3_RUN``/``ICESEE_EXAMPLE``/``ICESEE_RUN_SCRIPT``), plus the
    MPI/ensemble parameters (``ICESEE_NP``/``ICESEE_NENS``/
    ``ICESEE_MODEL_NPROCS``) a real ICESEE Batch entrypoint would read to
    run the exact same ``mpirun -np "$ICESEE_NP" python "$ICESEE_RUN_SCRIPT"
    -F params.yaml --Nens="$ICESEE_NENS"
    --model_nprocs="$ICESEE_MODEL_NPROCS"`` command Remote already runs.
    MPI env vars are only added when a value is actually supplied (``None``
    -- e.g. a serial example -- adds nothing), never fabricated."""
    env = [
        {"name": "ICESEE_S3_RUN", "value": s3_run},
        {"name": "ICESEE_EXAMPLE", "value": example_name},
        {"name": "ICESEE_RUN_SCRIPT", "value": run_script_name},
    ]
    if np is not None:
        env.append({"name": "ICESEE_NP", "value": str(np)})
    if nens is not None:
        env.append({"name": "ICESEE_NENS", "value": str(nens)})
    if model_nprocs is not None:
        env.append({"name": "ICESEE_MODEL_NPROCS", "value": str(model_nprocs)})
    return env


def aws_batch_submit(
    cfg: AWSBatchConfig,
    local_run_dir: Path,
    example_name: str,
    run_script_name: str,
    *,
    np: int | None = None,
    nens: int | None = None,
    model_nprocs: int | None = None,
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

    env = build_icesee_container_env(
        s3_run=s3_run, example_name=example_name, run_script_name=run_script_name,
        np=np, nens=nens, model_nprocs=model_nprocs,
    )

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


#: In-image example -> absolute runtime directory, for examples whose
#: cloud execution has actually been verified end-to-end (2026-09-08,
#: bkyanjo/icesee-combined:v1.0.1, digest
#: sha256:e393b1eed21f3481fffcfb3bb7ce5ce315fbff0cc8dc0fe4f2bcc2e2f1d538ed):
#: pulled, `with-icesee` activated, `import ICESEE`/mpi4py/h5py all
#: succeeded, and `mpirun --allow-run-as-root -np 1 python
#: run_da_lorenz96.py -F params.yaml --Nens=N --model_nprocs=M --verbose`
#: ran to completion with real output
#: (results/true-wrong-lorenz.h5 + _modelrun_datasets/*.h5). An example not
#: listed here has no verified cloud path yet -- the runner below refuses
#: it by name rather than guessing a path that was never actually run.
ICESEE_VERIFIED_EXAMPLES: dict[str, str] = {
    "lorenz96": "/opt/ICESEE/applications/lorenz_model/examples/lorenz96",
}

#: Only single-rank (NP=1) execution is verified. NP>1 was tried against
#: the same image/example and found unsafe: the default (serial) execution
#: mode has no MPI-rank coordination, so every rank redundantly regenerates
#: the same shared HDF5 files and races on them (BlockingIOError), while
#: the top-level exception handler in ICESEE.src.run_model_da.run_models_da
#: swallows the failure and exits 0 -- a false success. The genuinely
#: parallel modes (execution_mode 1 "partial"/2 "full" in params.yaml) were
#: also tried: "full" hard-crashes because this image's h5py has no MPI I/O
#: support (`driver='mpio'` -> "h5py was built without MPI support"), and
#: "partial" hits an unrelated example/config bug
#: (icesee_get_index: object of type 'NoneType' has no len()) -- neither is
#: a container defect this runner can work around. Rather than silently
#: accept a value that is known to race or crash, the runner below refuses
#: any ICESEE_NP != 1 outright.
ICESEE_VERIFIED_MAX_NP = 1

_ICESEE_RUNNER = r"""#!/usr/bin/env bash
# =====================================================================
# ICESEE cloud runner  (auto-generated -- do not edit)
# =====================================================================
set -uo pipefail

log()  { printf '[icesee-cloud] %s\n' "$*" >&2; }
fail() { log "ERROR ($1): $2"; exit "$1"; }

: "${ICESEE_S3_RUN:?ICESEE_S3_RUN is required}"
: "${ICESEE_EXAMPLE:?ICESEE_EXAMPLE is required}"
: "${ICESEE_RUN_SCRIPT:?ICESEE_RUN_SCRIPT is required}"
NP="${ICESEE_NP:-1}"
NENS="${ICESEE_NENS:-1}"
MODEL_NPROCS="${ICESEE_MODEL_NPROCS:-0}"
WORKDIR="${ICESEE_WORKDIR:-/tmp/icesee/run}"

command -v aws >/dev/null 2>&1 || fail 3 "the batch container has no 'aws' CLI (needed for S3 I/O)"

if [ "${NP}" != "1" ]; then
  fail 65 "ICESEE_NP=${NP} is not verified for cloud execution -- only single-rank (ICESEE_NP=1) runs have been verified end-to-end against this runtime; multi-rank runs race on shared HDF5 output files (or crash: h5py in this image has no MPI I/O support) and are refused rather than silently producing wrong results"
fi

case "${ICESEE_EXAMPLE}" in
  lorenz96)
    EXAMPLE_DIR="/opt/ICESEE/applications/lorenz_model/examples/lorenz96"
    ;;
  *)
    fail 64 "unverified ICESEE example: ${ICESEE_EXAMPLE} (only lorenz96 has a verified cloud runtime path)"
    ;;
esac

SCRIPT="${EXAMPLE_DIR}/${ICESEE_RUN_SCRIPT}"
[ -f "${SCRIPT}" ] || fail 66 "run script not found in the image: ${SCRIPT}"

log "phase 1/3  fetch  ${ICESEE_S3_RUN}/params.yaml  ->  ${WORKDIR}"
mkdir -p "${WORKDIR}" || fail 4 "cannot create ${WORKDIR}"
aws s3 cp "${ICESEE_S3_RUN}/params.yaml" "${WORKDIR}/params.yaml" --only-show-errors \
    || fail 4 "params.yaml download failed"

log "phase 2/3  run  example=${ICESEE_EXAMPLE} np=${NP} nens=${NENS} model_nprocs=${MODEL_NPROCS}"
with-icesee mpirun --allow-run-as-root -np "${NP}" python "${SCRIPT}" \
    -F "${WORKDIR}/params.yaml" --Nens="${NENS}" --model_nprocs="${MODEL_NPROCS}" --verbose
rc=$?
log "model runtime exit code: ${rc}"

log "phase 3/3  sync  outputs  ->  ${ICESEE_S3_RUN}/outputs/"
if [ -d "${EXAMPLE_DIR}/results" ]; then
  aws s3 sync "${EXAMPLE_DIR}/results/" "${ICESEE_S3_RUN}/outputs/results/" --only-show-errors \
      || log "WARNING: results output sync failed (model rc=${rc})"
fi
if [ -d "${EXAMPLE_DIR}/_modelrun_datasets" ]; then
  aws s3 sync "${EXAMPLE_DIR}/_modelrun_datasets/" "${ICESEE_S3_RUN}/outputs/_modelrun_datasets/" --only-show-errors \
      || log "WARNING: dataset output sync failed (model rc=${rc})"
fi

exit "${rc}"
"""


def build_icesee_batch_runner() -> str:
    """The ICESEE Batch job-definition entrypoint script -- reads the exact
    ``ICESEE_S3_RUN``/``ICESEE_EXAMPLE``/``ICESEE_RUN_SCRIPT``/``ICESEE_NP``/
    ``ICESEE_NENS``/``ICESEE_MODEL_NPROCS`` contract
    :func:`build_icesee_container_env` already produces, and runs the same
    ``with-icesee`` + ``mpirun`` command shape verified locally against
    ``bkyanjo/icesee-combined:v1.0.1`` (2026-09-08). See
    :data:`ICESEE_VERIFIED_EXAMPLES` / :data:`ICESEE_VERIFIED_MAX_NP` for
    what that verification actually covered."""
    return _ICESEE_RUNNER


def icesee_batch_command() -> list[str]:
    """The AWS Batch job-definition ``command`` that runs the ICESEE
    runner -- the same ``["bash", "-c", <script>]`` shape as CryoStack's own
    generic cloud runner (``cryostack_src.cloud.runtime.cloud_run_command``),
    kept as a separate function/script because ICESEE is not one of
    ``cryostack_src.cloud.runtime.SUPPORTED_CLOUD_MODELS`` and uses its own
    env-var contract, never the generic ``CRYOSTACK_*`` one."""
    return ["bash", "-c", build_icesee_batch_runner()]


def aws_batch_status(cfg: AWSBatchConfig, job_id: str, *, aws=None) -> dict:
    code, out, err = _run(cfg, ["batch", "describe-jobs", "--jobs", job_id], aws=aws)
    if code != 0:
        raise RuntimeError(err or out)
    job = json.loads(out)["jobs"][0]
    return {"status": job.get("status", "?"), "reason": job.get("statusReason", "")}


def sync_cloud_outputs(
    cfg: AWSBatchConfig, s3_run: str, local_dir: Path, *, aws=None,
) -> bool:
    """Sync ``s3://<s3_run>/outputs/`` into ``local_dir`` (a run's own
    ``workspace_directory``) -- the S3 -> local run-cache step of the
    lifecycle diagram (local run -> stage inputs -> S3 -> AWS execution ->
    outputs/ -> S3 -> run cache -> ResultPackage -> Workspace Results).

    A real ICESEE Batch entrypoint is expected to mirror the SAME
    ``results/``/``figures/`` layout ``discover_result_package()`` already
    reads locally, so no new discovery code is needed -- whatever lands in
    ``local_dir`` after this call is picked up by the existing DA-aware
    ResultPackage unchanged.

    Returns whether the ``aws s3 sync`` command itself succeeded (exit 0).
    This is NOT a claim that any file was actually found -- an empty/not-
    yet-populated S3 prefix syncs successfully and produces nothing; the
    caller (or discover_result_package) is the ground truth for that."""
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    code, out, err = _run(
        cfg, ["s3", "sync", f"{s3_run.rstrip('/')}/outputs/", str(local_dir)], aws=aws,
    )
    if code != 0:
        raise RuntimeError(err or out)
    return True


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
    np: int | None = None,
    nens: int | None = None,
    model_nprocs: int | None = None,
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
    resp = aws_batch_submit(
        cfg, rd, example_name, find_run_script(example_cfg).name,
        np=np, nens=nens, model_nprocs=model_nprocs, aws=aws,
    )

    messages = [
        "[cloud] Submitted.",
        f"batch_job_id: {resp['batch_job_id']}",
        f"s3_run      : {resp['s3_run']}",
        "",
        "[batch image requirement]",
        "Your AWS Batch container must read ICESEE_S3_RUN and ICESEE_RUN_SCRIPT,",
        "download params.yaml from S3, run, then sync results back to S3.",
    ]
    if np is not None and np > MAX_SINGLE_TASK_MPI_RANKS:
        messages.append(
            f"[warning] ICESEE_NP={np} exceeds this codebase's single-Fargate-task "
            f"ceiling ({MAX_SINGLE_TASK_MPI_RANKS} vCPUs) -- AWS Batch on Fargate "
            "cannot run a multi-node MPI job; a real ICESEE Batch job definition "
            "would need an EC2-backed compute environment for this ensemble size."
        )

    return CloudSubmitResult(
        success=True,
        run_dir=rd,
        batch_job_id=resp["batch_job_id"],
        s3_run=resp["s3_run"],
        run_id=resp["run_id"],
        messages=messages,
    )
