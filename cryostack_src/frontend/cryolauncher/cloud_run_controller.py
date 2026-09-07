# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Cloud Run Controller
# File        : cloud_run_controller.py
#
# Description :
#     Non-blocking submit + auto-poll + auto-retrieve for an AWS Batch cloud
#     run, on the same asyncio worker/state pattern the auto-tail log worker
#     uses (cryostack_src/workspace/logs.py).
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""CryoStack cloud run controller (C6).

Owns one cloud run's lifecycle so the gateway callback never blocks the Voilà
kernel:

    submit()  -> STAGING -> SUBMITTING -> (job id) -> QUEUED
              -> auto-poll -> RUNNING -> COMPLETED / FAILED / CANCELLED
              -> on COMPLETED: auto-sync outputs -> Results panel refresh

Every AWS call runs in a worker thread (:func:`asyncio.to_thread`); the
controller only touches widget state on the event loop. It converges on the
existing services -- ``CloudBridge`` for submit/status/logs/terminate,
``WorkspaceManager.sync_cloud_results`` for retrieval, the shared
``ResultPackage`` / visualizer for rendering -- and adds no parallel path.

This module holds **no ipywidgets import**: the gateway passes plain callables
(`on_state`, `on_log`, `on_results_ready`) so the controller stays unit
testable with fakes.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Callable

# ── states ────────────────────────────────────────────────────────────────
NOT_CONFIGURED = "not_configured"
CHECKING = "checking"
READY = "ready"
STAGING = "staging"
SUBMITTING = "submitting"
QUEUED = "queued"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"

CLOUD_STATES: tuple[str, ...] = (
    NOT_CONFIGURED, CHECKING, READY, STAGING, SUBMITTING,
    QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED,
)
_TERMINAL: frozenset[str] = frozenset({COMPLETED, FAILED, CANCELLED})

#: AWS Batch raw state -> CryoStack state (mirrors CloudBackend._normalize_state,
#: plus the two AWS states that have no CloudStatus mapping)
_AWS_STATE_MAP = {
    "SUBMITTED": QUEUED, "PENDING": QUEUED, "RUNNABLE": QUEUED,
    "STARTING": RUNNING, "RUNNING": RUNNING,
    "SUCCEEDED": COMPLETED, "FAILED": FAILED,
}


def is_terminal(state: str) -> bool:
    return state in _TERMINAL


def normalize_aws_state(raw: str) -> str:
    return _AWS_STATE_MAP.get((raw or "").strip().upper(), QUEUED)


# ── failure classification ────────────────────────────────────────────────
#: (predicate on the lowercased message, short user-facing message)
_FAILURE_RULES: tuple[tuple[str, str], ...] = (
    (r"could not connect to the endpoint|name resolution|network is unreachable",
     "Cannot reach AWS. Check your network and region."),
    (r"unable to locate credentials|no credentials|credentials not found|"
     r"expiredtoken|invalidclienttokenid|the security token included in the request is",
     "AWS credentials are not configured. Run `aws configure` (or set a profile) and retry."),
    (r"the config profile .* could not be found|profilenotfound|invalid profile",
     "That AWS profile does not exist. Fix the profile name under Advanced."),
    (r"could not connect to the endpoint url.*\bregion\b|invalid region|"
     r"illegal location constraint|the bucket is in this region",
     "Region mismatch. Set the region to match your bucket and Batch resources."),
    (r"not a valid s3 bucket name|s3 location must be a bucket|"
     r"invalid bucket name|the s3 bucket name is empty|not a usable s3 key prefix",
     "The S3 bucket / location is not valid. Enter a bucket name or an "
     "s3://bucket URI."),
    (r"nosuchbucket|bucket does not exist|not staging.*bucket|needs an s3 bucket",
     "The S3 bucket is missing. Prepare cloud storage or fix the bucket name."),
    (r"accessdenied|access denied|forbidden|not authorized to perform",
     "Access denied by AWS. Your identity lacks permission for this bucket / queue / job."),
    (r"repositorynotfoundexception|image .* not found|no such image|manifest unknown",
     "The container image is not in ECR. Prepare cloud compute (image push) first."),
    (r"job queue .* does not exist|jobqueue .* not found|invalid job queue",
     "The Batch job queue does not exist. Prepare cloud compute first."),
    (r"job definition .* does not exist|jobdefinition .* not found|"
     r"invalid job definition|revision .* is not valid",
     "The Batch job definition does not exist. Prepare cloud compute first."),
    (r"could not access your aws account|connection is not verified|"
     r"connection could not be refreshed|reconnect the aws account|"
     r"assumed session belongs to a different aws account|"
     r"account for this connection changed|account mismatch|"
     r"missing its role arn or externalid",
     "Your AWS connection could not be refreshed. Re-check the connected AWS "
     "account in Cloud Environment → AWS ACCOUNT and try again."),
    (r"matlab licens", "ISSM could not start because a usable MATLAB license "
                       "was not available from the cloud environment. "
                       "Infrastructure can still be tested with the smoke test."),
    (r"execution descriptor failed|failed to upload the staged run|"
     r"staged run directory does not exist|run target .* is not present",
     "Could not stage the run inputs to S3. Check the working copy and the run target."),
    (r"submit-job failed|could not read a jobid|aws batch submit-job",
     "AWS Batch rejected the submission. See the log for the exact reason."),
    (r"cloud results sync failed|no cloud run location|output .* not found|"
     r"outputs/ is empty",
     "The job finished but its S3 outputs could not be retrieved."),
    (r"schema|metadata\.json|result package|resulterror|not readable",
     "The job produced outputs but the result package is malformed."),
    (r"\bfailed\b.*exit|job failed|essential container|task failed",
     "The Batch job ran but failed. Open the log for the container error."),
    (r"timed out|timeout", "The Batch job hit its time limit before finishing."),
)


def classify_cloud_failure(error: Any) -> tuple[str, str]:
    """Map an exception / message to ``(short_actionable, full_detail)``.

    The short message is safe to show a user; the detail is the original text
    for the log. Never returns a secret -- the inputs are already screened
    upstream, and this only pattern-matches.
    """
    detail = str(error).strip()
    low = detail.lower()
    for pattern, short in _FAILURE_RULES:
        if re.search(pattern, low):
            return short, detail
    return ("The cloud operation failed. See the log for details.", detail or "unknown error")


# ── job-definition controlled selection ───────────────────────────────────
def resolve_job_definition(
    model: str, override: str, *, allow_list: dict[str, str],
) -> tuple[str, list[str]]:
    """Return ``(job_definition, warnings)``.

    Selection is controlled: the model's deterministic name is the default, and
    an override is accepted **only** if it names a known CryoStack job
    definition (optionally with a ``:revision`` suffix). Anything else is
    ignored with a warning -- a UI/agent free string can never pick an
    arbitrary Batch job definition.
    """
    model = (model or "").strip().lower()
    default = allow_list.get(model, f"cryostack-{model}")
    ov = (override or "").strip()
    if not ov:
        return default, []
    base = ov.split(":", 1)[0]
    if base in allow_list.values() or base == default:
        return ov, []
    return default, [
        f"Ignoring job-definition override {ov!r}: not a CryoStack job "
        f"definition. Using {default!r}."
    ]


# ── cost / resource preview ───────────────────────────────────────────────
def cloud_run_plan_summary(
    *, model: str, region: str, bucket: str, job_queue: str, job_definition: str,
    vcpu: str = "2", memory_mib: str = "8192", timeout_seconds: int = 3600,
) -> str:
    """A short pre-submit summary. No dollar figure -- AWS pricing depends on
    the account, so we state the resources and that charges apply."""
    gib = "?"
    try:
        gib = f"{int(memory_mib) / 1024:.0f}"
    except (TypeError, ValueError):
        pass
    return (
        "This submits an AWS Batch (Fargate) job. It will use AWS resources "
        "and may incur charges on your account.\n"
        f"  model          {model}\n"
        f"  region         {region}\n"
        f"  S3 bucket      {bucket}\n"
        f"  job queue      {job_queue}\n"
        f"  job definition {job_definition}\n"
        f"  resources      {vcpu} vCPU · {gib} GiB · time limit "
        f"{int(timeout_seconds) // 60} min (from the job definition)\n"
        "  outputs        s3://<bucket>/runs/<user>/<run-id>/outputs/  -> your run cache"
    )


# ── user-scoped S3 prefix ─────────────────────────────────────────────────
_S3_SEG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def user_run_prefix(safe_user_id: str) -> str:
    """``<safe-user>/`` -- the S3 key prefix under ``runs/`` that isolates one
    CryoStack user's cloud runs from another's.

    Pass ``WorkspaceManager.owner.safe_id`` (already a collision-resistant,
    filesystem-safe namespace key). A defensive re-slug here guarantees a
    single clean path segment even if a caller hands a raw id.
    """
    seg = _S3_SEG_RE.sub("-", (safe_user_id or "").strip()).strip("-.") or "user"
    return f"{seg[:64]}/"


# ── the controller ────────────────────────────────────────────────────────
@dataclass
class _RunHandle:
    job_id: str = ""
    s3_run: str = ""
    run_id: str = ""
    model: str = ""
    state: str = NOT_CONFIGURED
    region: str = ""
    profile: str | None = None
    metadata: dict = field(default_factory=dict)
    # -- C7.5: BYO-AWS + review context for the active-run surface --------
    #: the connected AWS account this run belongs to ("" = developer mode)
    account_id: str = ""
    example: str = ""
    #: canonical resource shape, for display only
    vcpu: float = 0.0
    memory_gib: float = 0.0
    expected_runtime_minutes: float = 0.0
    #: retained non-secret CloudCostEstimate.to_public_dict() -- for the live
    #: accumulated-cost display; NO pricing call is made during the run.
    cost_public: dict = field(default_factory=dict)
    #: the review digest this run was launched from (drift audit only)
    review_digest: str = ""
    #: the CryoStack tested container image this run executes in -- carried
    #: to the CLOUD RUN card and frozen into the run manifest at submit so a
    #: historical run never drifts when the default image changes.
    image_key: str = ""
    image_label: str = ""
    image_reference: str = ""
    image_digest: str = ""
    #: non-secret AWS resource identity for the diagnostics menu -- SEEDED at
    #: submit (job id, region, queue, job definition, s3 run, image) and grown
    #: by each DescribeJobs poll (log stream, ECS task ARN, resolved ARNs).
    #: Never a credential / token / ExternalId (merge_aws_resources enforces).
    aws_resources: dict = field(default_factory=dict)
    #: monotonic seconds when the run left STAGING (set by the ticker owner)
    started_at: float = 0.0


class CloudRunController:
    """One-per-gateway owner of the active cloud run's async lifecycle."""

    def __init__(
        self,
        *,
        bridge_factory: Callable[..., Any],
        register_run: Callable[..., Any],
        sync_results: Callable[..., Any],
        on_state: Callable[[str], None],
        on_log: Callable[[str], None],
        on_results_ready: Callable[[], None] = lambda: None,
        execution_provider: Callable[[], Any] | None = None,
        on_run_view: Callable[..., None] | None = None,
        on_resources: Callable[[str, dict], None] | None = None,
        poll_interval: float = 15.0,
        to_thread: Callable[..., Any] = asyncio.to_thread,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._bridge_factory = bridge_factory
        self._register_run = register_run
        self._sync_results = sync_results
        self._on_state = on_state
        self._on_log = on_log
        self._on_results_ready = on_results_ready
        #: (job_id, aws_resources) -> None. Fired whenever the non-secret
        #: resource snapshot grows -- the gateway persists it into the run
        #: manifest so the diagnostics menu survives a page refresh and a
        #: historical run keeps its OWN resources.
        self._on_resources = on_resources
        #: () -> CloudExecution. When set, EVERY AWS operation for this run
        #: (stage, submit, poll, logs, terminate, result sync) is performed
        #: with a FRESH context from this -- a fresh sts:AssumeRole for a
        #: connected BYO account. It raises CloudAccessError for a broken
        #: connection; there is no ambient/profile fallback.
        self._execution_provider = execution_provider
        self._on_run_view = on_run_view
        self._poll_interval = max(0.0, float(poll_interval))
        self._to_thread = to_thread
        self._sleep_fn = sleep

        self._handle = _RunHandle()
        self._task = None                       # the single active lifecycle task

    # -- public state ----------------------------------------------------
    @property
    def state(self) -> str:
        return self._handle.state

    @property
    def job_id(self) -> str:
        return self._handle.job_id

    def _set_state(self, state: str) -> None:
        self._handle.state = state
        try:
            self._on_state(state)
        except Exception:
            pass
        self._emit_view()

    def _emit_view(self) -> None:
        if self._on_run_view is None:
            return
        h = self._handle
        try:
            self._on_run_view(
                state=h.state, model=h.model, example=h.example,
                account_id=h.account_id, region=h.region,
                vcpu=h.vcpu, memory_gib=h.memory_gib,
                expected_runtime_minutes=h.expected_runtime_minutes,
                cost_public=dict(h.cost_public), job_id=h.job_id,
                image_label=h.image_label, image_reference=h.image_reference,
                image_digest=h.image_digest,
                aws_resources=dict(h.aws_resources),
                terminal=is_terminal(h.state),
            )
        except Exception:
            pass

    def _seed_resources(self) -> None:
        """The resource identity already known once a job id exists -- no AWS
        call, all from the handle."""
        h = self._handle
        self._merge_resources({
            "region": h.region,
            "account_id": h.account_id,
            "batch_job_id": h.job_id,
            "s3_run": h.s3_run,
            "image_reference": h.image_reference,
            "image_digest": h.image_digest,
            **({k: v for k, v in (h.metadata or {}).items()
                if k in ("job_queue", "job_definition")}),
        })

    def _merge_resources(self, updates: dict) -> None:
        """Fold non-secret resource identity into the snapshot; emit if it
        grew. Never makes an AWS call -- callers pass what a poll already
        returned."""
        from cryostack_src.cloud.diagnostics import merge_aws_resources

        before = self._handle.aws_resources
        after = merge_aws_resources(before, updates)
        if after == before:
            return
        self._handle.aws_resources = after
        if self._on_resources is not None and self._handle.job_id:
            try:
                self._on_resources(self._handle.job_id, dict(after))
            except Exception:
                pass

    def _log(self, message: str) -> None:
        try:
            self._on_log(message)
        except Exception:
            pass

    def _log_auth(self, operation: str, execution) -> None:
        """Temporary, secret-free diagnostic: which credential context is
        about to be used for one AWS operation -- proves, from the run log
        itself, that a fresh assumed-role session (not the host's ambient
        identity) is what reaches AWS for each lifecycle step. Never an ARN,
        ExternalId, access key, token, or secret -- only the bound account
        id and whether the context is a temporary role or developer mode."""
        account = (
            self._handle.account_id
            or (getattr(execution, "account_id", "") or "")
        ).strip() or "none"
        access = "temporary-role" if getattr(execution, "is_byo", False) else "developer-mode"
        self._log(f"[cloud][auth] {operation} account={account} access={access}")

    # -- credential context: fresh per AWS operation --------------------
    def _resolve_execution(self):
        """Fresh CloudExecution for one AWS operation. Raises CloudAccessError
        for a broken BYO connection -- callers fail closed, never fall back."""
        if self._execution_provider is None:
            return None
        return self._execution_provider()

    def _bridge(self, execution=None):
        """A CloudBridge bound to the current credential context.

        BYO-AWS: assumed-role temporary credentials (fresh). Developer mode
        (no execution provider): the existing ambient/profile bridge.

        When ``execution`` is not supplied (poll / terminate / status calls
        that resolve their own context), the freshly resolved account is
        checked against the run's recorded ``account_id`` -- a run attached
        for account A must never be polled/terminated against whichever
        account is CURRENTLY connected (B). ``run_once`` already resolves +
        asserts once and passes ``execution`` in explicitly, so it is not
        re-checked here.
        """
        if self._execution_provider is None:
            return self._bridge_factory()
        ex = execution if execution is not None else self._resolve_execution()
        if execution is None:
            self._assert_same_account(ex)
        creds = getattr(ex, "credentials", None)
        region = getattr(ex, "region", None) or self._handle.region or None
        return self._bridge_factory(credentials=creds, region=region)

    def _assert_same_account(self, execution) -> None:
        """A run recorded for a connected BYO account (``self._handle.
        account_id`` set) must NEVER touch AWS through anything but a fresh,
        verified assumed-role session for that SAME account -- never
        cross-account, and never a silent fall-through to ambient/profile
        (host service) credentials.

        Fails closed on BOTH failure shapes, not just a mismatched account:

        * ``execution`` is not BYO at all (``is_byo`` false / absent) --
          e.g. ``resolve_cloud_execution`` momentarily found no connection
          record and degraded to developer/ambient mode. Before this check
          existed, that case slipped past the old ``want and got`` test
          (an empty ``got`` made the condition false) and the run went on to
          use whatever ambient/profile identity the CryoStack host itself
          runs as -- the exact live defect (SubmitJob correctly used the
          assumed-role Account-B session; every subsequent poll/terminate
          silently fell through to the host's own ``cryostack-service`` IAM
          identity and AWS correctly denied ``batch:DescribeJobs``).
        * ``execution`` IS BYO but for a DIFFERENT account than this run was
          reviewed for (the original cross-account guard).

        A developer-mode RUN (``self._handle.account_id`` empty -- no BYO
        connection was ever involved) has nothing to enforce and is
        unaffected by this method.
        """
        want = (self._handle.account_id or "").strip()
        if not want:
            return
        if not getattr(execution, "is_byo", False):
            raise RuntimeError(
                "Could not access your AWS account for this run "
                f"(account {want}). Not falling back to host/ambient "
                "credentials -- re-check the connected AWS account in "
                "Cloud Environment → AWS ACCOUNT and try again."
            )
        got = (getattr(execution, "account_id", "") or "").strip()
        if got != want:
            raise RuntimeError(
                "account mismatch: this run was reviewed for AWS account "
                f"{want} but the connected account is now {got or 'unknown'}. "
                "Not proceeding."
            )

    # -- submit --------------------------------------------------------
    def submit(self, **submit_kwargs) -> None:
        """Kick off the whole lifecycle (stage -> submit -> poll -> retrieve)
        on the event loop and return at once.

        ``submit_kwargs`` (minus the ``_region`` / ``_profile`` /
        ``_md_provenance`` hints) are forwarded verbatim to
        ``CloudBridge.submit`` -- the gateway is responsible for having already
        run ``validate_cloud_config`` + ``cloud_run_preflight`` and staged the
        user-owned working copy.
        """
        if self._task is not None and not self._task.done():
            self._log("[cloud] A cloud run is already in progress.")
            return
        self._handle = _RunHandle(
            model=(submit_kwargs.get("model") or "").strip().lower(),
            region=submit_kwargs.pop("_region", "") or "",
            profile=submit_kwargs.pop("_profile", None),
            metadata=dict(submit_kwargs.pop("_md_provenance", None) or {}),
            account_id=(submit_kwargs.pop("_account_id", "") or "").strip(),
            example=(submit_kwargs.pop("_example", "") or "").strip(),
            vcpu=float(submit_kwargs.pop("_vcpu", 0) or 0),
            memory_gib=float(submit_kwargs.pop("_memory_gib", 0) or 0),
            expected_runtime_minutes=float(
                submit_kwargs.pop("_expected_runtime_minutes", 0) or 0),
            cost_public=dict(submit_kwargs.pop("_cost_public", None) or {}),
            review_digest=(submit_kwargs.pop("_review_digest", "") or ""),
            image_key=(submit_kwargs.pop("_image_key", "") or "").strip(),
            image_label=(submit_kwargs.pop("_image_label", "") or "").strip(),
            image_reference=(submit_kwargs.pop("_image_reference", "") or "").strip(),
            image_digest=(submit_kwargs.pop("_image_digest", "") or "").strip(),
        )
        self._task = self._spawn(self.run_once(**submit_kwargs))

    async def run_once(self, **submit_kwargs) -> None:
        """The full lifecycle as one coroutine (Voilà spawns it as a task;
        tests ``asyncio.run`` it directly)."""
        try:
            self._set_state(STAGING)
            # fresh credential context for the WHOLE submit (stage + submit-job);
            # for a connected BYO account this is a fresh sts:AssumeRole and it
            # must resolve to the account the run was reviewed for.
            execution = await self._to_thread(self._resolve_execution)
            self._assert_same_account(execution)
            self._log_auth("submit", execution)
            self._set_state(SUBMITTING)
            self._log("[cloud] Staging inputs to S3 and submitting to AWS Batch…")
            result = await self._to_thread(
                lambda: self._bridge(execution).submit(**submit_kwargs)
            )
            job_id = getattr(result, "job_id", None)
            meta = getattr(result, "metadata", {}) or {}
            s3_run = meta.get("s3_run") or getattr(result, "working_directory", None)
            run_id = meta.get("run_id")
            for m in getattr(result, "messages", []) or []:
                self._log(str(m))
            if not job_id or not s3_run:
                raise RuntimeError(
                    "submit-job did not return a job id / S3 run location")
            self._handle.job_id = str(job_id)
            self._handle.s3_run = str(s3_run)
            self._handle.run_id = str(run_id or job_id)
            # fold the submit-result's own non-secret job facts into the
            # diagnostics snapshot (job queue / job definition it resolved)
            self._merge_resources({
                "job_queue": meta.get("job_queue"),
                "job_definition": meta.get("job_definition"),
            })
            self._seed_resources()
            self._log(f"[cloud] Submitted. job id {job_id}")
            try:
                self._register_run(handle=self._handle, result=result)
            except Exception as reg_err:  # registration must not lose the run
                self._log(f"[cloud] (run registration warning) {reg_err}")
            self._set_state(QUEUED)
            await self._poll_loop(self._handle.job_id)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 -- surfaced, classified
            short, detail = classify_cloud_failure(error)
            self._log(f"[cloud][ERROR] {short}")
            self._log(f"[cloud][detail] {detail}")
            self._set_state(FAILED)

    # -- polling ------------------------------------------------------
    def start_polling(self, job_id: str, *, s3_run: str = "", model: str = "") -> None:
        """Re-attach polling to an already-submitted job (no new submission)."""
        if not job_id:
            return
        if self._task is not None and not self._task.done():
            return  # duplicate-poll guard
        self._handle.job_id = str(job_id)
        if s3_run:
            self._handle.s3_run = s3_run
        if model:
            self._handle.model = model
        self._task = self._spawn(self._poll_loop(str(job_id)))

    async def _poll_loop(self, job_id: str) -> None:
        while not is_terminal(self._handle.state):
            # Credential/account resolution is checked SEPARATELY from the
            # AWS status call: a broken connection or an account switch
            # underneath an in-flight run (this run is A's, the user is now
            # connected to B) is not a transient hiccup to retry forever --
            # it must fail closed and stop polling.
            try:
                execution = await self._to_thread(self._resolve_execution)
                self._assert_same_account(execution)
                self._log_auth("poll", execution)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                short, detail = classify_cloud_failure(error)
                self._log(f"[cloud][ERROR] {short}")
                self._log(f"[cloud][detail] {detail}")
                self._set_state(FAILED)
                return

            try:
                status = await self._to_thread(
                    lambda: self._bridge(execution).status(job_id=job_id))
                state = getattr(status, "state", "") or normalize_aws_state(
                    getattr(status, "raw_state", ""))
                reason = getattr(status, "reason", "") or ""
            except Exception as poll_err:  # transient AWS/CLI hiccup: keep polling
                self._log(f"[cloud] status check failed, retrying: {poll_err}")
                await self._sleep(self._poll_interval)
                continue

            # grow the diagnostics snapshot from what THIS poll revealed
            # (log stream, ECS task ARN, resolved queue / job-definition
            # ARNs, container image) -- no extra AWS call, all from the
            # DescribeJobs result we already have.
            try:
                from cryostack_src.cloud.diagnostics import resources_from_poll

                self._merge_resources(
                    resources_from_poll(getattr(status, "metadata", {}) or {}))
            except Exception:
                pass

            if state and state != self._handle.state:
                self._set_state(state)
                self._log(f"[cloud] {state}"
                          + (f" — {reason}" if reason and state == FAILED else ""))

            if state == COMPLETED:
                await self._retrieve_results()
                return
            if state in (FAILED, CANCELLED):
                return
            await self._sleep(self._poll_interval)

    async def _retrieve_results(self) -> None:
        self._log("[cloud] Job completed. Retrieving outputs from S3…")
        try:
            execution = await self._to_thread(self._resolve_execution)
            self._assert_same_account(execution)
            self._log_auth("results", execution)
            creds = getattr(execution, "credentials", None)
            region = getattr(execution, "region", None) or self._handle.region or None
            path = await self._to_thread(
                lambda: self._sync_results(
                    s3_uri=self._handle.s3_run,
                    region=region,
                    profile=None if creds else self._handle.profile,
                    credentials=creds,
                )
            )
            self._log(f"[cloud] Outputs synced to {path}")
            self._on_results_ready()
        except Exception as error:  # noqa: BLE001
            short, detail = classify_cloud_failure(error)
            self._log(f"[cloud][ERROR] {short}")
            self._log(f"[cloud][detail] {detail}")
            # the job DID complete; keep COMPLETED, just report the sync failure

    # -- terminate --------------------------------------------------
    def terminate(self, job_id: str = "") -> None:
        job_id = str(job_id or self._handle.job_id)
        if not job_id:
            self._log("[cloud] No job to terminate.")
            return
        self._spawn(self._terminate_worker(job_id))

    async def _terminate_worker(self, job_id: str) -> None:
        try:
            self._log(f"[cloud] Requesting termination of job {job_id}…")
            # a BYO run terminates through a FRESH context for the SAME
            # account, never through host ambient credentials. Resolved and
            # asserted explicitly here (same shape as poll/results) so the
            # diagnostic log and the AWS call both use this ONE checked
            # execution -- not a second, separately-resolved one internal to
            # _bridge()'s own no-argument fallback.
            execution = await self._to_thread(self._resolve_execution)
            self._assert_same_account(execution)
            self._log_auth("terminate", execution)
            await self._to_thread(
                lambda: self._bridge(execution).terminate(job_id=job_id))
            self._set_state(CANCELLED)      # stops the poll loop on its next check
            self._log("[cloud] Termination requested.")
        except Exception as error:  # noqa: BLE001
            short, detail = classify_cloud_failure(error)
            self._log(f"[cloud][ERROR] {short}")
            self._log(f"[cloud][detail] {detail}")

    # -- lifecycle -------------------------------------------------
    def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None

    def attach(self, *, job_id: str, s3_run: str, model: str = "",
               region: str = "", profile: str | None = None,
               account_id: str = "", example: str = "",
               vcpu: float = 0.0, memory_gib: float = 0.0,
               expected_runtime_minutes: float = 0.0, cost_public: dict | None = None,
               image_key: str = "", image_label: str = "",
               image_reference: str = "", image_digest: str = "",
               aws_resources: dict | None = None,
               state: str = QUEUED) -> None:
        """Re-attach to a run that already exists (e.g. selected from run
        history after a kernel restart) and resume polling if it is not
        terminal. Status/log/terminate/retrieve then use a FRESH context for
        the recorded ``account_id`` (BYO) -- no persisted STS credentials.

        ``image_*`` and ``aws_resources`` come from the run manifest so the
        CLOUD RUN card + diagnostics menu reflect THIS run, not the current
        Cloud Environment defaults."""
        from cryostack_src.cloud.diagnostics import merge_aws_resources

        self._handle = _RunHandle(
            job_id=str(job_id), s3_run=str(s3_run), model=model,
            region=region, profile=profile, state=state,
            account_id=(account_id or "").strip(), example=example,
            vcpu=float(vcpu or 0), memory_gib=float(memory_gib or 0),
            expected_runtime_minutes=float(expected_runtime_minutes or 0),
            cost_public=dict(cost_public or {}),
            image_key=(image_key or "").strip(),
            image_label=(image_label or "").strip(),
            image_reference=(image_reference or "").strip(),
            image_digest=(image_digest or "").strip(),
            aws_resources=merge_aws_resources({}, aws_resources or {}),
        )
        # backfill anything the persisted snapshot did not have (older runs)
        self._seed_resources()
        self._set_state(state)
        if not is_terminal(state):
            self.start_polling(str(job_id))

    # -- internals ------------------------------------------------
    def _spawn(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            return loop.create_task(coro)          # Voilà / async context
        # no running loop (print-mode / a test that used submit()): run to
        # completion now. A test that wants step control awaits run_once itself.
        return asyncio.run(coro)

    async def _sleep(self, seconds: float) -> None:
        # chunked so stop()/cancel() is responsive
        remaining = float(seconds)
        if remaining <= 0:
            await self._sleep_fn(0)
            return
        while remaining > 0 and not is_terminal(self._handle.state):
            await self._sleep_fn(min(0.5, remaining))
            remaining -= 0.5
