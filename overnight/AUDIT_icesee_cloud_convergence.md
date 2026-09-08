# ICESEE Cloud ↔ CryoLauncher Cloud convergence audit (read-only)

Coordinating session, 2026-09-08. Branch `gatech_vm_backend`. Continues the
ICESEE parity port (commits `d8441b2`..`ac108b5`) into the one gap that
port explicitly deferred: ICESEE Cloud still runs on the legacy
`icesee_jupyter_book/core/cloud_runner.py`, independent of CryoLauncher's
`CloudBridge` / `CloudBackend` / `CloudManager` / `AWSDriver` stack.

## Test-count reconciliation (exact, not estimated)

The earlier "1704 passed, 1 skipped" figure is from commit `67c2e810`
(2026-09-07, `cloud(icepack): preserve figure metadata...`)'s own message:
*"Full three-directory suite: 1704 passed, 1 skipped (clean env; the one
failure with ambient CRYOSTACK_AWS_PRINCIPAL_ARN set is the pre-existing
environmental one)."*

- **The three directories are `cryostack_src` + `icesee_jupyter_book` +
  `icesee_hpc_connector`** — confirmed by `pytest --collect-only` at
  `67c2e810` (via an isolated `git worktree`, no working-tree mutation):
  1362 + 277 + 66 = **1705 collected** = 1704 passed + 1 skipped. `deployment`
  (60 tests) is a fourth, separate suite not part of this figure.
- My own last report's "1697 passed" covered only **two** of those three
  directories (`cryostack_src` + `icesee_jupyter_book`) — it omitted
  `icesee_hpc_connector` entirely. That is the whole discrepancy; no tests
  were lost.
- Today (HEAD `ac108b5`), the correct three-directory collection is
  1388 + 311 + 66 = **1765 collected**. Executed: **1763 passed, 1 skipped,
  1 failed** (`test_missing_principal_shows_a_clear_config_error`).
- That one failure is the SAME pre-existing environmental one named in the
  `67c2e810` message: this sandbox session has `CRYOSTACK_AWS_PRINCIPAL_ARN`
  set ambiently (confirmed via `env`), and the test expects it unset.
  Reproduced identically by running that one test at `67c2e810` under
  today's ambient env: same failure, same commit, same cause. Not a
  regression.
- Net collected-test delta 1765 − 1705 = **60 new tests**, added across the
  12 commits between `67c2e810` and `ac108b5` (6 from this session's ICESEE
  parity port, 6 from the preceding overnight session) — `git log --oneline
  67c2e81..HEAD -- cryostack_src icesee_jupyter_book icesee_hpc_connector`
  lists exactly those 12, no others.
- Aside: a `git worktree` checkout of an old commit initially showed 7-8
  *additional* failures in `cryostack_src/tests/test_app_warmup_routes.py`.
  Traced to `FileNotFoundError` on `external/living-ice-sheet-temperature/
  frontend/dist` and `icesee_jupyter_book/_build` — both are **untracked,
  locally-built artifacts**, not part of git history, and therefore absent
  from a fresh worktree. Copying them from the main tree made the failures
  disappear. This is a pre-existing test-hygiene gap (a hermetic-looking
  suite with an actual dependency on locally-built, untracked directories)
  worth knowing about, not a code regression — noted here, not fixed (out
  of scope for this audit).

## A. What CryoLauncher Cloud actually is (the mature side)

`cryostack_src/execution/backend.py` defines the provider-neutral contract
CryoStack is migrating everything onto ("CryoStack strangler migration",
its own docstring's term): `ExecutionResult` / `ExecutionStatus` /
`ExecutionBackend.{submit,status,logs,terminate}`.

`cryostack_src/execution/cloud.py::CloudBackend` implements that contract
for the cloud. Its own docstring: *"During the strangler migration, the
backend wraps the existing AWS Batch implementation in
`icesee_jupyter_book.core.cloud_runner`* [sic — CryoLauncher's own history,
not ICESEE's] *rather than replacing it... Cloud submission functions can
be supplied dynamically so that ICESEE and CryoLauncher may initially
continue using their existing submission implementations while sharing the
same execution interface."* **This was already built with ICESEE
convergence as a named intent.**

`CloudBackend.submit(**kwargs)` → `CloudManager.submit(submitter=...)` →
`AWSDriver.submit(**kwargs)`:
```python
if self._submitter is not None:
    return self._submitter(**kwargs)     # legacy path — wins, unconditionally
# else: assert_cloud_run_allowed -> stage_run_inputs (S3) -> submit_batch_job
```
`CloudBackend.submit`'s own result-normalization code reads BOTH a dict
with `batch_job_id`/`s3_run`/`messages`/`run_id` (**exactly ICESEE's
`CloudSubmitResult` shape**) and a dataclass/object with the same
attributes — the dict branch is shaped for ICESEE specifically, not
speculatively.

`status` / `logs` / `terminate` do **not** consult `self._submitter` — they
always call `cryostack_src.cloud.legacy.aws_batch.{batch_status,batch_logs,
terminate_batch_job}` against `self.config` (an `AWSConfig`: region /
profile / credentials, fixed at driver-construction time). These three
operations only need a Batch `job_id` — they are already provider-generic
and don't care whether the job was submitted by CryoLauncher's staged-tree
path or by a raw `aws batch submit-job` call with different env vars.
**This is the single biggest converge-for-free opportunity**: ICESEE can
route status/logs/terminate through the real hardened driver today, with
zero change to the AWS side, because those operations never touch the
submission contract.

Credential handling (`cryostack_src/cloud/drivers/aws/auth.py::run_aws`):
assumed-role `credentials` (temporary STS triple) **replace** ambient
`AWS_PROFILE` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` /
`AWS_SESSION_TOKEN` / `AWS_SECURITY_TOKEN` in the subprocess env — never
inherited, never combined with `--profile`. `cryostack_src/cloud/legacy/
aws_batch.py` keeps an intentionally-duplicated copy of this same
credential-stripping logic, with a comment explaining exactly why (a real,
already-fixed C7.5 bug: `DescribeJobs`/`Terminate` once silently used
ambient host credentials instead of the assumed-role session one layer
below the controller). **This is the exact failure mode to avoid
reproducing for ICESEE.**

## B. What ICESEE Cloud actually is today

`icesee_jupyter_book/core/cloud_runner.py` (170 lines): `AWSBatchConfig`
(region/profile/**no credentials field**), `_aws_cmd`/`_run` (raw
`subprocess.run` with **no `env=` override at all** — ambient AWS
credentials pass straight through unconditionally, unlike either
CryoLauncher implementation), `aws_batch_submit` (upload `params.yaml` +
a `cloud_manifest.json` to `s3://.../<run_id>/`, then `aws batch
submit-job` with three env vars: `ICESEE_S3_RUN` / `ICESEE_EXAMPLE` /
`ICESEE_RUN_SCRIPT`), `aws_batch_status` (`describe-jobs` →
`{status, reason}` — same shape as CryoLauncher's `batch_status`),
`submit_cloud_example` (the public entry point, called directly from
`icesee_gateway.py`'s `run_example_cloud_submit`). **No terminate
function exists at all** — the gateway's Cloud tab has no Terminate
button (`terminate_btn` is wired Remote-only; disabled whenever mode is
Cloud). No BYO-AWS account concept (no `AWSConnection`, no AssumeRole, no
persisted per-user connection) — `aws_profile`/`aws_region` are bare text
fields the user types directly, mirroring CryoLauncher's *pre-C7*
developer/ambient mode, not its BYO-AWS mode.

## C. ICESEE-specific semantics that must survive unflattened

| Semantic | Where it lives today | Carrier once ported |
|---|---|---|
| Ensemble size / member layout | `enkf-parameters.Nens`, `ensemble`/`ensemble_mean` h5 datasets | `DAIdentity.ensemble_size` (`run_records.py`, already built); `results_package.py` ensemble category (already built) |
| Forecast/analysis cycle | `true_state`/`nurged_state` h5 datasets, `dt`/`num_years`/`timesteps_per_year` | `DAIdentity` DA-cycle fields; `results_package.py` forecast category |
| Observations | `hu_obs`/`R` h5 datasets, `freq_obs`/`obs_*_time`/`sig_obs` | `DAIdentity` observation fields; `results_package.py` observations category |
| Filter/assimilation method | `enkf-parameters.filter_type` (`EnKF\|DEnKF\|EnTKF\|EnRSKF`) | `DAIdentity.assimilation_filter` |
| State variables / estimated parameters | `vec_inputs`/`observed_vars`, `state_estimation`/`parameter_estimation`/`joint_estimation` | `DAIdentity` |
| Multi-process/MPI | `enkf-parameters.parallel_flag` (`serial\|MPI\|MPI_model`), `cluster_mpi_np` | **Not yet carried anywhere in the cloud path** — see gap below |
| Run directories | `run_dir(base, name)` → `results/`, `figures/` | Unchanged; `run_records.py` already scopes it per-user |
| Ensemble/result collection | ad-hoc `rglob` on `results/*.h5` | `results_package.py` (already built, Phase 3/4 of the parity port) |
| Current cloud command construction | `aws batch submit-job --container-overrides '{"environment":[ICESEE_S3_RUN, ICESEE_EXAMPLE, ICESEE_RUN_SCRIPT]}'` | Must stay byte-identical unless/until a real `cryostack-icesee` image changes what the container expects — **out of scope for this session (needs a provisioned image + job def; genuine external boundary)** |

**Real gap found, not previously flagged**: nothing in the current ICESEE
cloud path threads `parallel_flag`/`cluster_mpi_np` into the AWS Batch
container at all — an MPI ICESEE example submitted to Cloud today would
run exactly as if `parallel_flag=serial`, silently. This predates this
session and is **unrelated to the convergence work** (the container image
doesn't support MPI execution yet either); recorded here so it isn't lost,
not fixed now.

## D. Mapping onto mature CryoStack primitives

| ICESEE concept | Maps onto |
|---|---|
| `AWSBatchConfig` | `cryostack_src.cloud.drivers.aws.auth.AWSConfig` / `cryostack_src.cloud.legacy.aws_batch.AWSConfig` (already kept in lockstep with each other) |
| `submit_cloud_example` | `CloudBridge.submit(**kwargs)` with an **injected submitter** — the exact hook `CloudBackend`/`AWSDriver` already document existing for this |
| `aws_batch_status` | `CloudBridge.status(job_id=...)` → real `AWSDriver.status` → `cloud.legacy.aws_batch.batch_status` (same `{status,reason}` shape — **direct replacement, no shim needed**) |
| *(nothing)* | `CloudBridge.terminate(job_id=...)` → real `AWSDriver.terminate` → `cloud.legacy.aws_batch.terminate_batch_job` (**new ICESEE capability**, zero AWS-side change) |
| Local `.cryostack-run.json` | Already wired (`run_records.py`, prior commits) |
| Ad-hoc H5 preview | Already superseded by `results_package.py` for local inspection; S3 result sync is a separate, larger piece (`CloudBridge.results()`, needs a `results_sync` callable — **not built for ICESEE in this session**, see stopping point) |
| *(nothing)* | `cryostack_src.cloud.diagnostics` (`merge_aws_resources`/`resources_from_poll`/`aws_console_links`) — pure, already shareable per the prior audit |

## E. Staged migration plan for this session (repo-local, no AWS contact)

1. **`core/cloud_runner.py`**: make `AWSBatchConfig` credential-aware
   (`credentials` field) and route its subprocess execution through the
   SAME credential-stripping logic CryoLauncher already tested twice
   (`cryostack_src.cloud.legacy.aws_batch.AWSConfig`/`run_aws`) instead of
   ICESEE's current unconditional ambient passthrough. Make the `aws`
   invocation injectable (mirrors `submit_batch_job(..., aws=None)`'s
   existing pattern) so tests never touch a real `aws` binary. Add
   `terminate_cloud_job`. **Additive, backward-compatible** — no existing
   caller's signature changes.
2. **New `icesee_jupyter_book/core/cloud_bridge_adapter.py`**: builds a
   `CloudBridge` with a submitter closure that preserves ICESEE's exact
   upload/env-var contract from step 1's (now credential-aware) functions.
   Status and terminate go through the bridge's real hardened path — no
   submitter involved, since (per §A) those never depended on the
   submission contract. Parity tests assert the constructed `aws` argv is
   byte-identical to what the legacy path issues today.
3. **Gateway wiring** (`icesee_gateway.py`): Cloud tab's submit/status
   move onto the adapter; a genuinely new Terminate button/handler is
   added (parity with Remote's, and with CryoLauncher Cloud). `STATUS`
   dict keys (`batch_job_id`, `s3_run`) and `run_records` recording are
   preserved/updated to the new result shape. The legacy `cloud_runner.py`
   functions are **not deleted** — they are now the adapter's own
   implementation, exercised through it. No dual-path flag is introduced
   (unnecessary: the adapter *is* the legacy contract, just credential-hardened
   and lifecycle-wrapped).
4. **Explicitly NOT done this session** (genuine external/infra boundary,
   matching the earlier ICESEE-parity audit's own conclusion, unchanged
   by this work): a provisioned `cryostack-icesee` container image + Batch
   job definition, BYO-AWS onboarding for ICESEE (Connect AWS Account UI +
   persisted `AWSConnection`), S3 result sync into a local `ResultPackage`,
   and MPI-aware container command construction. All four require either
   contacting AWS or a real container build, both out of scope here.
