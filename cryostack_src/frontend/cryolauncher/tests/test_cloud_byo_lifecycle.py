"""C7.5 -- the BYO-AWS cloud run lifecycle through CloudRunController.

Offline: every AWS boundary is a fake. Proves each lifecycle operation
(stage/submit, poll, terminate, result sync) runs with a FRESH assumed-role
context for the reviewed account, never falls back to ambient/profile, and
that a broken connection or account mismatch fails closed.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.connect.execution import CloudAccessError, CloudExecution
from cryostack_src.frontend.cryolauncher.cloud_run_controller import (
    CANCELLED,
    COMPLETED,
    FAILED,
    RUNNING,
    CloudRunController,
)

BYO_A = {"AWS_ACCESS_KEY_ID": "ASIA_A", "AWS_SECRET_ACCESS_KEY": "s", "AWS_SESSION_TOKEN": "t"}


async def _immediate(fn):
    return fn()


async def _no_sleep(_s):
    return None


class _Status:
    def __init__(self, state):
        self.state = state
        self.raw_state = state.upper()
        self.reason = ""


class _SubmitResult:
    job_id = "job-A1"
    working_directory = None
    metadata = {"s3_run": "s3://cryostack-runs-713938953301/runs/u/x", "run_id": "x"}
    messages = ["submitted"]


class RecordingBridge:
    """bridge_factory(**kw) returns a fresh one per AWS op (mirrors a fresh
    AssumeRole). Poll state is SHARED at class level -- like real AWS job
    state, it does not reset when a new session is created."""

    instances: list = []
    poll_sequence: list = [RUNNING, RUNNING, COMPLETED]
    _poll_i: int = 0

    def __init__(self, *, credentials=None, region=None, profile=None):
        self.credentials = credentials
        self.region = region
        self.profile = profile
        RecordingBridge.instances.append(self)

    def submit(self, **kw):
        return _SubmitResult()

    def status(self, *, job_id):
        seq = RecordingBridge.poll_sequence
        state = seq[min(RecordingBridge._poll_i, len(seq) - 1)]
        RecordingBridge._poll_i += 1
        return _Status(state)

    def terminate(self, *, job_id):
        return {"ok": True}


@pytest.fixture(autouse=True)
def _reset():
    RecordingBridge.instances = []
    RecordingBridge.poll_sequence = [RUNNING, RUNNING, COMPLETED]
    RecordingBridge._poll_i = 0
    yield


def _byo_execution(account="713938953301", *, calls=None):
    def provider():
        if calls is not None:
            calls.append(1)
        return CloudExecution(mode="byo", region="us-east-2", credentials=dict(BYO_A),
                              profile=None, account_id=account)

    return provider


def _controller(*, execution_provider, bridge_factory=None, **over):
    sink = {"states": [], "logs": [], "synced": [], "views": []}

    def _sync(**kw):
        sink["synced"].append(kw)
        return "/local/cloud_outputs"

    ctl = CloudRunController(
        bridge_factory=bridge_factory or (lambda **kw: RecordingBridge(**kw)),
        register_run=lambda **kw: None,
        sync_results=_sync,
        on_state=sink["states"].append,
        on_log=sink["logs"].append,
        on_run_view=lambda **v: sink["views"].append(v),
        execution_provider=execution_provider,
        poll_interval=0.0,
        to_thread=_immediate,
        sleep=_no_sleep,
        **over,
    )
    return ctl, sink


# -- A. BYO launch -----------------------------------------------
def test_every_operation_uses_a_fresh_assume_role_and_the_temp_creds():
    calls = []
    ctl, sink = _controller(execution_provider=_byo_execution(calls=calls))
    ctl.submit(
        staged_source="/tmp/x", model="issm", run_target="runme.m",
        bucket="cryostack-runs-713938953301", _account_id="713938953301",
    )
    # submit + 3 polls + retrieve == 5 fresh resolves (one per AWS op)
    assert len(calls) >= 5
    # every bridge built carried the assumed-role creds, never a profile
    assert RecordingBridge.instances
    for b in RecordingBridge.instances:
        assert b.credentials == BYO_A
        assert b.profile is None
    assert sink["synced"][-1]["credentials"] == BYO_A
    assert sink["synced"][-1]["profile"] is None
    assert COMPLETED in sink["states"]


def test_reviewed_account_and_resources_ride_the_handle_to_the_view():
    ctl, sink = _controller(execution_provider=_byo_execution())
    ctl.submit(
        staged_source="/tmp/x", model="issm", run_target="runme.m",
        bucket="cryostack-runs-713938953301",
        _account_id="713938953301", _example="SquareIceShelf",
        _vcpu=2, _memory_gib=8, _expected_runtime_minutes=5,
        _cost_public={"available": True, "estimated_total_usd": 0.01,
                      "expected_runtime_minutes": 5},
    )
    v = sink["views"][-1]
    assert v["account_id"] == "713938953301" and v["example"] == "SquareIceShelf"
    assert v["vcpu"] == 2 and v["memory_gib"] == 8


# -- B. fail closed -------------------------------------------
def test_broken_byo_connection_fails_closed_no_ambient_fallback():
    def boom():
        raise CloudAccessError("Your AWS connection could not be refreshed.")

    ctl, sink = _controller(execution_provider=boom)
    ctl.submit(
        staged_source="/tmp/x", model="issm", run_target="runme.m",
        bucket="cryostack-runs-713938953301", _account_id="713938953301",
    )
    assert sink["states"][-1] == FAILED
    assert RecordingBridge.instances == []          # no bridge, no AWS call
    assert any("Re-check the connected AWS account" in m for m in sink["logs"])


def test_account_mismatch_blocks_submission_before_any_aws_call():
    # provider now resolves to account B, but the run was reviewed for A
    ctl, sink = _controller(execution_provider=_byo_execution("774888247882"))
    ctl.submit(
        staged_source="/tmp/x", model="issm", run_target="runme.m",
        bucket="cryostack-runs-713938953301", _account_id="713938953301",
    )
    assert sink["states"][-1] == FAILED
    assert RecordingBridge.instances == []
    assert any("account" in m.lower() and "mismatch" in m.lower()
               for m in sink["logs"])


# -- C. developer mode --------------------------------------
def test_developer_mode_has_no_execution_provider_and_uses_the_plain_bridge():
    plain = RecordingBridge(credentials=None, region=None, profile="cryo-dev")
    RecordingBridge.instances = []
    sink = {"states": [], "logs": []}
    ctl = CloudRunController(
        bridge_factory=lambda: plain,               # no kwargs -- classic path
        register_run=lambda **kw: None,
        sync_results=lambda **kw: "/local",
        on_state=sink["states"].append,
        on_log=sink["logs"].append,
        execution_provider=None,                    # developer mode
        poll_interval=0.0, to_thread=_immediate, sleep=_no_sleep,
    )
    ctl.submit(staged_source="/tmp/x", model="issm",
               run_target="runme.m", bucket="b", _profile="cryo-dev")
    assert COMPLETED in sink["states"]


# -- D. lifecycle + cancellation --------------------------
def test_lifecycle_states_progress_staging_to_completed():
    ctl, sink = _controller(execution_provider=_byo_execution())
    ctl.submit(staged_source="/tmp/x", model="issm",
               run_target="runme.m", bucket="b", _account_id="713938953301")
    seq = [s for s in sink["states"]]
    assert seq.index("staging") < seq.index("submitting") < seq.index("queued")
    assert seq[-1] == COMPLETED


def test_terminate_uses_a_fresh_context_for_the_same_account():
    ctl, sink = _controller(execution_provider=_byo_execution())
    ctl._handle.job_id = "job-A1"
    ctl._handle.account_id = "713938953301"
    asyncio.run(ctl._terminate_worker("job-A1"))
    assert ctl.state == CANCELLED
    assert RecordingBridge.instances[-1].credentials == BYO_A
    assert RecordingBridge.instances[-1].profile is None


# -- E. account-switch isolation: a selected run keeps its OWN account -----
def test_terminate_fails_closed_when_connected_account_diverges_from_the_run():
    """A run recorded under account A, terminated while the CryoStack user is
    now connected to account B (they used "Change AWS account"), must never
    reach AWS with B's credentials pretending to be A's job. It must fail
    closed and touch no bridge."""
    ctl, sink = _controller(execution_provider=_byo_execution("774888247882"))  # now on B
    ctl._handle.job_id = "job-A1"
    ctl._handle.account_id = "713938953301"                                     # run is A's
    asyncio.run(ctl._terminate_worker("job-A1"))
    assert ctl.state != CANCELLED               # never claims success
    assert RecordingBridge.instances == []       # no AWS call was made
    assert any("account" in m.lower() and "mismatch" in m.lower()
               for m in sink["logs"])


def test_poll_fails_closed_when_connected_account_diverges_from_the_run():
    ctl, sink = _controller(execution_provider=_byo_execution("774888247882"))  # now on B
    ctl._handle.job_id = "job-A1"
    ctl._handle.account_id = "713938953301"                                     # run is A's
    asyncio.run(ctl._poll_loop("job-A1"))
    assert COMPLETED not in sink["states"]
    assert RecordingBridge.instances == []       # the mismatch is caught before
                                                  # any AWS status call is made


def test_result_retrieval_fails_closed_when_connected_account_diverges():
    ctl, sink = _controller(execution_provider=_byo_execution("774888247882"))  # now on B
    ctl._handle.job_id = "job-A1"
    ctl._handle.s3_run = "s3://cryostack-runs-713938953301/runs/u/x"
    ctl._handle.account_id = "713938953301"                                     # run is A's
    asyncio.run(ctl._retrieve_results())
    assert sink["synced"] == []                  # never synced using B's creds
    assert any("account" in m.lower() and "mismatch" in m.lower()
               for m in sink["logs"])



# -- F. live-incident regression: developer-mode fallback loophole ---------
# Reproduces job ec56a332-7832-4933-936d-e98f236d0e37 (account 774888247882):
# SubmitJob correctly used a fresh BYO AssumeRole, but every poll (and then
# Terminate) reached AWS Batch as arn:aws:iam::713938953301:user/
# cryostack-service and was denied. `_assert_same_account`'s old
# ``want and got`` test only fired when BOTH sides were non-empty -- a
# developer-mode CloudExecution (``is_byo`` False, ``account_id`` "" by
# dataclass default) made `got` empty and silently passed the guard, letting
# `_bridge()` build a bridge with the host's own ambient/profile identity.
class AmbientBridge:
    """Stands in for whatever AWS identity the CryoStack host itself runs
    as (e.g. cryostack-service) -- constructed whenever a bridge is built
    with no assumed-role credentials. Its mere construction during an
    account-bound run's poll/terminate/retrieve IS the live defect."""

    instances: list = []

    def __init__(self, *, credentials=None, region=None, profile=None):
        self.credentials = credentials
        self.region = region
        self.profile = profile
        AmbientBridge.instances.append(self)

    def submit(self, **kw):
        return _SubmitResult()

    def status(self, *, job_id):
        return _Status(RUNNING)

    def terminate(self, *, job_id):
        return {"ok": True}


def _mixed_bridge_factory(**kw):
    """Mirrors the live gateway's ``current_cloud_bridge``: credentials
    present -> the assumed-role bridge; credentials absent -> whatever the
    host's own ambient/profile identity is (here, the sentinel that proves
    the defect if it is ever reached)."""
    if kw.get("credentials"):
        return RecordingBridge(**kw)
    return AmbientBridge(**kw)


@pytest.fixture(autouse=True)
def _reset_ambient():
    AmbientBridge.instances = []
    yield


def _degrading_provider(byo_account="774888247882", calls=None):
    """First call (submit) resolves BYO for the reviewed account -- exactly
    like the live incident, where SubmitJob succeeded. Every call after that
    "degrades" to developer mode with no account at all, reproducing
    whatever transient condition made ``resolve_cloud_execution`` return
    ``CloudExecution(mode="developer", account_id="")`` on the very next
    poll -- the trigger the live incident showed but this suite does not
    need to pin down to prove the boundary holds regardless."""
    state = {"n": 0}

    def provider():
        state["n"] += 1
        if calls is not None:
            calls.append(state["n"])
        if state["n"] == 1:
            return CloudExecution(mode="byo", region="us-east-2",
                                  credentials=dict(BYO_A), profile=None,
                                  account_id=byo_account)
        return CloudExecution(mode="developer", region="us-east-2",
                              credentials=None, profile=None, account_id="")

    return provider


def test_poll_fails_closed_when_the_connection_degrades_to_developer_mode():
    """The exact live defect for polling: submit is BYO, the very next poll
    resolves developer mode. Must fail closed -- never reach AmbientBridge,
    i.e. never touch batch:DescribeJobs as the host's own identity."""
    ctl, sink = _controller(
        execution_provider=_degrading_provider(),
        bridge_factory=_mixed_bridge_factory,
    )
    ctl.submit(
        staged_source="/tmp/x", model="issm", run_target="runme.m",
        bucket="cryostack-runs-774888247882", _account_id="774888247882",
    )
    assert AmbientBridge.instances == []          # never reached DescribeJobs as ambient
    assert sink["states"][-1] == FAILED            # fails closed, not stuck retrying forever
    assert any("host/ambient credentials" in m or "could not access your aws account" in m.lower()
               for m in sink["logs"])


def _developer_mode_provider():
    """Always resolves developer mode -- simulates the connection having
    already degraded by the time this single AWS operation resolves its own
    fresh context (exactly what terminate/result-retrieval each do: one
    ``_resolve_execution()`` call per invocation)."""
    return CloudExecution(mode="developer", region="us-east-2",
                          credentials=None, profile=None, account_id="")


def test_terminate_fails_closed_when_the_connection_degrades_to_developer_mode():
    """The exact live defect for terminate: a BYO-bound run, but by the time
    Terminate is clicked the freshly-resolved execution is developer mode.
    Must fail closed before any AmbientBridge is even constructed."""
    ctl, sink = _controller(
        execution_provider=_developer_mode_provider,
        bridge_factory=_mixed_bridge_factory,
    )
    ctl._handle.job_id = "job-A1"
    ctl._handle.account_id = "774888247882"
    asyncio.run(ctl._terminate_worker("job-A1"))
    assert ctl.state != CANCELLED
    assert AmbientBridge.instances == []
    assert any("host/ambient credentials" in m or "could not access your aws account" in m.lower()
               for m in sink["logs"])


def test_result_retrieval_fails_closed_when_the_connection_degrades_to_developer_mode():
    ctl, sink = _controller(
        execution_provider=_developer_mode_provider,
        bridge_factory=_mixed_bridge_factory,
    )
    ctl._handle.job_id = "job-A1"
    ctl._handle.s3_run = "s3://cryostack-runs-774888247882/runs/u/x"
    ctl._handle.account_id = "774888247882"
    asyncio.run(ctl._retrieve_results())
    assert sink["synced"] == []
    assert any("host/ambient credentials" in m or "could not access your aws account" in m.lower()
               for m in sink["logs"])


def test_live_incident_submit_poll_terminate_with_ambient_creds_deliberately_available():
    """The full submit -> poll -> terminate path from the live incident, in
    one test, with a real "ambient identity" (AmbientBridge / cryostack-
    service-shaped) deliberately reachable in the test environment via
    ``_mixed_bridge_factory`` the whole time. Submit succeeds on BYO (poll
    sequence resolves the job COMPLETED before any degrade would matter for
    submit itself); then, attached fresh with a provider that is ALWAYS
    developer-mode (simulating the connection having degraded by the time
    the user reattaches / clicks Terminate on page refresh), neither a
    fresh poll nor Terminate may ever construct AmbientBridge."""
    calls: list[int] = []
    ctl, sink = _controller(
        execution_provider=_byo_execution("774888247882", calls=calls),
        bridge_factory=_mixed_bridge_factory,
    )
    ctl.submit(
        staged_source="/tmp/x", model="icepack", run_target="run.py",
        bucket="cryostack-runs-774888247882", _account_id="774888247882",
    )
    assert COMPLETED in sink["states"]
    assert AmbientBridge.instances == []
    for b in RecordingBridge.instances:
        assert b.credentials == BYO_A                # never ambient, always the fresh assumed role

    # now simulate the connection having degraded (e.g. page refresh after
    # the BYO connection needed re-auth) and attempt to terminate the SAME
    # account-bound job -- must still never touch AmbientBridge.
    ctl2, sink2 = _controller(
        execution_provider=lambda: CloudExecution(
            mode="developer", region="us-east-2", credentials=None,
            profile=None, account_id=""),
        bridge_factory=_mixed_bridge_factory,
    )
    ctl2._handle.job_id = ctl._handle.job_id
    ctl2._handle.account_id = "774888247882"
    asyncio.run(ctl2._terminate_worker(ctl2._handle.job_id))
    assert ctl2.state != CANCELLED
    assert AmbientBridge.instances == []


def test_switching_accounts_does_not_disturb_an_unrelated_attached_run():
    """Attaching (selecting) a run for the account CURRENTLY connected still
    works normally after a "Change AWS account" -- the guard only blocks a
    genuine cross-account mismatch, never same-account use."""
    ctl, sink = _controller(execution_provider=_byo_execution("774888247882"))
    ctl.attach(job_id="job-B1", s3_run="s3://cryostack-runs-774888247882/runs/u/y",
               model="issm", region="us-east-2", account_id="774888247882",
               state=RUNNING)
    asyncio.run(ctl._terminate_worker("job-B1"))
    assert ctl.state == CANCELLED
    assert RecordingBridge.instances


# -- F. AWS diagnostics snapshot: seeded at submit, grown by each poll ----
class _StatusMeta:
    def __init__(self, state, metadata=None):
        self.state = state
        self.raw_state = state.upper()
        self.reason = ""
        self.metadata = metadata or {}


class _DiagBridge:
    """status() reveals more resource identity on each successive poll, like
    a real DescribeJobs (image at RUNNABLE, log stream + task ARN once the
    Fargate task starts)."""

    _i = 0

    def __init__(self, **kw):
        pass

    def submit(self, **kw):
        class _R:
            job_id = "job-D1"
            working_directory = None
            metadata = {"s3_run": "s3://cryostack-runs-774888247882/runs/u/x",
                        "run_id": "x", "job_queue": "cryostack-queue",
                        "job_definition": "cryostack-icepack:3"}
            messages = []
        return _R()

    def status(self, *, job_id):
        _DiagBridge._i += 1
        if _DiagBridge._i == 1:
            return _StatusMeta(RUNNING, {"region": "us-east-2",
                                         "image": "acct.dkr.ecr.us-east-2.amazonaws.com/cryostack-icepack@sha256:abc"})
        if _DiagBridge._i == 2:
            return _StatusMeta(RUNNING, {
                "region": "us-east-2",
                "log_stream": "cryostack-icepack/default/abcdef",
                "task_arn": "arn:aws:ecs:us-east-2:774888247882:task/AWSBatch-ce/deadbeef",
            })
        return _StatusMeta(COMPLETED, {"region": "us-east-2"})

    def terminate(self, *, job_id):
        return {"ok": True}


def test_diagnostics_snapshot_is_seeded_at_submit_and_grows_each_poll():
    _DiagBridge._i = 0
    emitted: list = []
    ctl, sink = _controller(
        execution_provider=_byo_execution("774888247882"),
        bridge_factory=lambda **kw: _DiagBridge(**kw),
        on_resources=lambda job_id, res: emitted.append((job_id, dict(res))),
    )
    ctl.submit(
        staged_source="/tmp/x", model="icepack", run_target="run.py",
        bucket="cryostack-runs-774888247882", _account_id="774888247882",
        _image_reference="bkyanjo/icesee-combined:v1.0.1",
        _image_digest="sha256:" + "e" * 64,
    )

    snap = ctl._handle.aws_resources
    # seeded at submit -- no poll needed
    assert snap["batch_job_id"] == "job-D1"
    assert snap["region"] == "us-east-2"
    assert snap["s3_run"].startswith("s3://cryostack-runs-774888247882/")
    assert snap["job_queue"] == "cryostack-queue"
    assert snap["job_definition"] == "cryostack-icepack:3"
    assert snap["image_reference"] == "bkyanjo/icesee-combined:v1.0.1"
    # grown by polling
    assert snap["log_stream"] == "cryostack-icepack/default/abcdef"
    assert snap["task_arn"].endswith("deadbeef")
    assert "dkr.ecr" in snap["image"]
    # on_resources fired incrementally, always with (job_id, dict), monotonic
    assert emitted and all(j == "job-D1" for j, _ in emitted)
    assert len(emitted[-1][1]) >= len(emitted[0][1])
    # never a credential in what was emitted
    blob = str(emitted)
    for banned in ("AWS_SECRET", "SESSION_TOKEN", "ASIA", "ExternalId"):
        assert banned not in blob


def test_diagnostics_are_restored_on_attach_from_the_persisted_snapshot():
    ctl, sink = _controller(execution_provider=_byo_execution("774888247882"))
    persisted = {
        "region": "eu-west-1", "batch_job_id": "hist-1",
        "s3_run": "s3://old-bucket/runs/u/r", "job_queue": "old-queue",
    }
    ctl.attach(job_id="hist-1", s3_run="s3://old-bucket/runs/u/r", model="icepack",
               region="eu-west-1", account_id="774888247882",
               aws_resources=persisted, state=COMPLETED)
    from cryostack_src.cloud.diagnostics import aws_console_links

    urls = " ".join(x["url"] for x in aws_console_links(ctl._handle.aws_resources))
    assert "eu-west-1" in urls and "hist-1" in urls
