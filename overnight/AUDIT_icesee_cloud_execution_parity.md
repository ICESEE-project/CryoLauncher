# ICESEE ↔ CryoLauncher Cloud execution-parity audit (read-only)

Coordinating session, 2026-09-08. Branch `gatech_vm_backend`, after the GUI
structural-parity checkpoint `bd7b0a9` (preserved, untouched by this work)
and the earlier cloud-convergence checkpoints (`3961316`..`d7953d7`, which
already moved ICESEE's submit/status/terminate onto `CloudBridge`/
`AWSDriver`). This audit covers what those checkpoints explicitly deferred:
BYO-AWS account parity, tested-image truthfulness, MPI-aware execution, S3
result sync, and provenance freezing.

## 1. BYO-AWS / Prepare Cloud — CryoLauncher vs ICESEE today

| Concept | CryoLauncher | ICESEE today |
|---|---|---|
| Connected account record | `AWSConnectionStore` (`.cryostack/cloud/aws-connection.json`), scoped to the **authenticated CryoStack user**, not the app | none |
| Credential resolution | `resolve_cloud_execution(user, model, region_hint, profile_hint)` → fresh `sts:AssumeRole` per operation, or developer/ambient fallback | raw `aws_region`/`aws_profile` text fields only (developer/ambient mode, forever) |
| Prepare Cloud | `CloudManager.bootstrap()` → storage/IAM/registry/Batch provisioning | none |
| Job queue / job definition defaults | `derive_cloud_defaults(account_id, region, model)` → `cryostack-queue`, `job_definition_name(model)`, `ECR_REPOSITORY_NAMES[model]` | user must type queue/job-definition by hand |
| Readiness states | `CloudManager.capabilities()` (`AWSCapabilities`: storage/network/iam/registry/batch, each independently `_ready`) | none — submit is attempted blind |

**Key finding:** `resolve_cloud_execution`, `derive_cloud_defaults`, and
`job_definition_name`/`ECR_REPOSITORY_NAMES` are **already model-agnostic**.
`derive_cloud_defaults(account_id=..., region=..., model="icesee")` returns
`job_definition="cryostack-icesee"`, `ecr_repository="cryostack-icesee"` via
their existing `.get(model, f"cryostack-{model}")` fallback — **zero changes
needed in `cryostack_src/cloud/connect/*` for ICESEE to participate**. And
because `AWSConnectionStore` is keyed by `WorkspaceUser`, not by
application, a user who already connected their AWS account **through
CryoLauncher's existing "Connect AWS Account" UI** has that same connection
available to ICESEE automatically — **no new UI is required in ICESEE** to
get BYO-AWS credential parity; only the backend needs to call the same
resolver. This is the single highest-leverage, lowest-risk convergence
available and is implemented in this session (see §Implementation, item 1).

`CloudManager.bootstrap()` (Prepare Cloud: storage/IAM/registry/Batch
provisioning) is model-agnostic already too, but *invoking* it for ICESEE
implies registering a **real** `cryostack-icesee` Batch job definition and
ECR repository in a real AWS account — a live action, out of reach here.
ICESEE can therefore resolve credentials and defaults through the shared
layer today; actually *preparing* those resources is the live boundary
reported at the end of this checkpoint.

## 2. Tested ICESEE cloud image — can it truthfully run ICESEE?

The registry (`cryostack_src/models/stack/images.py::TESTED_IMAGES`) has
exactly one entry, `icesee-combined-v1.0.1`
(`bkyanjo/icesee-combined:v1.0.1`), declaring
`models=("issm", "icepack")` — **"icesee" is not declared**, despite the
image's own name.

Inspecting `tools/cloud/Dockerfile` (the only artifact available without
pulling the image):

* it runs `python3 gen_pip_reqs.py --pyproject /opt/ICESEE/pyproject.toml`
  — this **requires `/opt/ICESEE` to already exist** in the base image
  (`docker.io/bkyanjo/combined-lean:v1.0`); this layer does not copy it in,
  so the ICESEE source tree is presumably baked into the base image already;
* it installs ICESEE's own pip dependencies (minus `numpy`/`mpi4py`/
  `petsc4py`/`h5py`, deliberately excluded — those are expected to already
  be present as MPI-aware, Spack-built wheels) into **both**
  `venv-icepack` and `venv-firedrake`;
* it defines `with-issm` (activates `/opt/venv-icesee` — a **fourth**,
  dedicated ICESEE virtualenv, distinct from icepack/firedrake) and a
  separate `with-icesee` wrapper that execs a base-image script,
  `/usr/local/bin/activate-icesee`, whose contents are not visible from
  this layer;
* `ENV ICESEE_MPI_ROOT` / a Spack-built OpenMPI 5.0.10 + HDF5 1.14.5 are
  wired into `with-issm`'s `PATH`/`LD_LIBRARY_PATH`, consistent with an
  MPI-capable runtime being present.

**Conclusion: the image very likely already contains an ICESEE-capable
Python environment and source tree, but this cannot be verified from the
repository alone** — `activate-icesee`'s actual contents, and whether
`venv-icesee` (or the icepack/firedrake venvs ICESEE's own deps were
installed into) can actually execute `external/ICESEE/applications/*/run_da_*.py`
end-to-end, live only in the built image or its build logs, neither
reachable without pulling `docker.io/bkyanjo/combined-lean:v1.0`/
`bkyanjo/icesee-combined:v1.0.1` — a registry contact explicitly out of
scope for this session.

**Decision: no new `TESTED_IMAGES` entry is added, and the existing
`icesee-combined-v1.0.1` entry's `models` tuple is NOT extended to include
`"icesee"`.** This registry's entire purpose is an end-to-end-validated
claim CryoStack provenance depends on; asserting "tested" without having
run so much as one example inside the image would be exactly the
fabricated-truthfulness this checkpoint was told to avoid. The exact
live verification needed is reported at the end of this checkpoint.

## 3. MPI-aware execution — the real ICESEE contract

From `icesee_jupyter_book/core/remote_runner.py`'s own SLURM template (the
one real, working parallel-execution contract ICESEE has today):

```sh
mpirun -np "${NP}" python "${RUN_SCRIPT}" -F "${PARAMS_PATH}" \
    --Nens="${NENS}" --model_nprocs="${MODEL_NPROCS}" --verbose
```

(`srun` is preferred when present, `mpirun` otherwise — both single
`-n`/`-np` launches, not a multi-node hostfile/topology.) `NP` = total MPI
ranks (`cluster_mpi_np` widget), `NENS` = ensemble size (`ens_sl`, already
shared across every mode), `MODEL_NPROCS` = per-ensemble-member process
count (`cluster_model_nprocs` widget) for `MPI_model`-parallel examples.
This is architecturally a **single co-located process group**: ICESEE
itself, not this codebase, decides how `NP` ranks split across ensemble
members (`parallel_flag`: `serial | MPI | MPI_model`) — CryoStack's job is
only to launch `NP` MPI processes together, which `mpirun -np NP ...`
already does without requiring any cross-host coordination.

**AWS Batch on Fargate implication:** Fargate runs one task as one
container with a fixed vCPU allocation (this codebase's own
`DEFAULT_MAX_VCPUS = 16` / `_FARGATE_MEMORY_RULES` ceiling at `"16"`
vCPUs, `cryostack_src/cloud/drivers/aws/batch_config.py`). A single Fargate
task can run `mpirun -np N` **entirely inside that one container** for any
`N` that fits the task's vCPU budget (OpenMPI spawns local processes; no
multi-host launch needed) — this is directly, correctly usable, not a
workaround, for `NP ≤ 16`. **Genuine limitation**: an ensemble whose real
`NP` exceeds one task's vCPU ceiling needs true multi-node MPI, which AWS
Batch supports only via **multi-node parallel jobs on EC2-backed compute
environments**, never Fargate — Fargate structurally cannot run a
multi-container co-scheduled MPI job. This is not fixable by any wiring
change; it is reported as the scientific/infra boundary, not silently
capped or hidden. Today's default compute environment
(`COMPUTE_ENVIRONMENT_NAME = "cryostack-fargate"`) is Fargate-only, so
until (if ever) an EC2 multi-node compute environment is added, ICESEE
Cloud submissions are honestly scoped to `NP ≤ 16` (documented, not
silently enforced as a made-up "cloud-only" algorithm).

**Implemented this session:** the container-override env-var contract
(`ICESEE_NP` / `ICESEE_NENS` / `ICESEE_MODEL_NPROCS`) that a real ICESEE
Batch job definition's entrypoint would read to run exactly the same
`mpirun -np NP ...` command Remote already runs — sourced from the SAME
`cluster_mpi_np`/`cluster_model_nprocs` widgets Remote already exposes (no
new UI). The job definition itself (an image + entrypoint that actually
reads these env vars and execs `mpirun`) is not registered anywhere real —
that also needs the live image/registry work in §2.

## 4-5. S3 staging / result sync / DA output contract

ICESEE's existing cloud submit path (`aws_batch_submit`) already uploads
`params.yaml` + `cloud_manifest.json` to
`s3://<bucket>/<prefix>/<run_id>/`. **Nothing pulls outputs back.** A
finished cloud run's `results/`/`figures/` stay empty locally forever —
`discover_result_package()` (the DA-aware ResultPackage, preserved as-is)
has nothing to discover. This is the second highest-leverage gap, and is
closed this session with a `sync_icesee_cloud_results()` step: `aws s3
sync s3://<s3_run>/outputs <run.workspace_directory>` using the SAME
credential-aware `run_aws` as every other cloud call, resolved from the
**run's own persisted `metadata["aws_resources"]`** (region, s3_run) plus
a **fresh** BYO-AWS credential resolution — never from whatever the Cloud
panel's text fields currently say, so a later visit to a historical run
re-syncs correctly regardless of what the user has since typed into the
region/bucket fields. `discover_result_package()` itself needs no changes:
it already discovers whatever is actually present under `results/` and
categorizes real ICESEE dataset names — synced outputs flow through the
same header-only HDF5 inspection with zero new code.

## 6-8. Workspace lifecycle / diagnostics / provenance

Runs/Files/Run Log/Results, run-record persistence, status refresh,
termination, and AWS-diagnostics metadata (`aws_resources`) are already
shared and working for ICESEE cloud runs (prior checkpoint). Reattachment
(resuming to watch/poll a cloud job after a kernel restart) is **not**
implemented for ICESEE and is not added this session — CryoLauncher's own
version depends on its `CloudRunController` auto-poll loop, a materially
larger piece of machinery ICESEE does not have and this checkpoint's scope
discipline says not to build speculatively. Provenance freezing (container
reference/digest, job-definition revision) cannot be populated honestly
yet because no real image/job-definition exists for ICESEE (§2) — the
manifest fields are wired to record them the moment a real one does,
without fabricating a value now.

## 9. ISSM licensing

Untouched. Not applicable to ICESEE (no MATLAB dependency); the existing
Secrets Manager ARN seam (`cryostack_src/cloud/matlab_license.py`,
`AWSConnection.matlab_license_secret_arn`, the Cloud Environment UI field)
is CryoLauncher-only and is not modified by this checkpoint.

## 10. What becomes genuinely shared vs. stays ICESEE-specific

| Shared (reused, zero/near-zero change) | ICESEE-specific (new/kept) |
|---|---|
| `resolve_cloud_execution` / `AWSConnectionStore` / `derive_cloud_defaults` | the `mpirun -np NP ... --Nens=NENS --model_nprocs=MODEL_NPROCS` command contract |
| `cryostack_src.cloud.legacy.aws_batch` (`AWSConfig`/`run_aws`/`batch_status`/`terminate_batch_job`) — already shared since the prior checkpoint | `discover_result_package` (DA-aware categorization) |
| `cryostack_src.cloud.diagnostics` (`merge_aws_resources`/`resources_from_poll`) — already shared | `DAIdentity` / `run_records.py` manifest metadata |
| `CloudBridge`/`CloudBackend`/`AWSDriver` lifecycle — already shared | the S3 `outputs/` → local `workspace_directory` sync step (ICESEE has no `WorkspaceManager.refresh_results()` equivalent to reuse; CryoLauncher's own sync is glaciological-model-shaped) |
| `job_definition_name`/`ECR_REPOSITORY_NAMES` fallback pattern | `IceseeRunsManager` / `IceseeCloudBridgeConfig` |

No new abstraction is extracted purely for its own sake — every item in
the left column already had exactly the shape ICESEE needed.

## Recommended smallest coherent convergence (this session)

1. Route ICESEE Cloud's credential/region/defaults resolution through
   `resolve_cloud_execution(model="icesee", ...)` — backend-only, no new UI,
   automatic BYO-AWS parity for any user who already connected an account.
2. Thread `cluster_mpi_np`/`cluster_model_nprocs` into the cloud
   container-override env vars (`ICESEE_NP`/`ICESEE_MODEL_NPROCS`),
   completing the MPI-aware execution contract, still zero UI change.
3. `sync_icesee_cloud_results()`: S3 → local workspace_directory, so
   Results becomes real and reproducible for a finished cloud run.
4. Freeze what is honestly knowable at submit time into the run manifest
   (execution mode, backend, region, run target, DA identity — already
   mostly wired; extend to cover what's newly available: BYO account id
   when connected, NP/model_nprocs).

Not done this session (genuine live boundaries, reported at the end):
registering a real `cryostack-icesee` Batch job definition/ECR repository,
verifying the tested image's ICESEE entrypoint by actually pulling/running
it, and any real `Prepare Cloud` invocation.
