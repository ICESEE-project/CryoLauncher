"""Cloud Commit 1 -- AWS Batch (Fargate) provisioning, describe-before-create,
idempotency. All AWS CLI calls are mocked; no real AWS resources are created.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.cloud.drivers.aws import batch as batch_mod
from cryostack_src.cloud.drivers.aws import batch_provision as bp
from cryostack_src.cloud.drivers.aws.batch_config import (
    DEFAULT_ISSM_JOB_CONFIG,
    container_properties_payload,
    job_definition_fingerprint,
)
from cryostack_src.cloud.drivers.aws.models import AWSConfig

CONFIG = AWSConfig(region="us-east-2")
SUBNETS = ["subnet-a", "subnet-b"]
SGS = ["sg-1"]
JOB_ROLE = "arn:aws:iam::123456789012:role/CryoStackJobRole"
EXEC_ROLE = "arn:aws:iam::123456789012:role/CryoStackExecutionRole"
IMAGE = "123456789012.dkr.ecr.us-east-2.amazonaws.com/cryostack-issm:tested"


class FakeAWS:
    """A minimal in-memory AWS Batch / Logs the provisioner can drive.

    ``ce_status_seq`` / ``queue_status_seq`` model the async ``status``
    transition AWS reports on successive ``describe-*`` calls (default: VALID
    immediately). Each ``describe-compute-environments`` / ``describe-job-queues``
    consumes one entry; the last entry sticks.
    """

    def __init__(self, *, ce_status_seq=None, queue_status_seq=None,
                 ce_status_reason="", queue_status_reason=""):
        self.calls: list[list[str]] = []
        self.compute_envs: list[dict] = []
        self.job_queues: list[dict] = []
        self.job_defs: list[dict] = []
        self.log_groups: set[str] = set()
        self._ce_seq = list(ce_status_seq or ["VALID"])
        self._q_seq = list(queue_status_seq or ["VALID"])
        self._ce_reason = ce_status_reason
        self._q_reason = queue_status_reason

    def _next_ce_status(self):
        s = self._ce_seq[0] if len(self._ce_seq) == 1 else self._ce_seq.pop(0)
        return s

    def _next_q_status(self):
        s = self._q_seq[0] if len(self._q_seq) == 1 else self._q_seq.pop(0)
        return s

    # -- helpers -------------------------------------------------------
    def count(self, *prefix) -> int:
        p = list(prefix)
        return sum(1 for c in self.calls if c[: len(p)] == p)

    def last(self, *prefix) -> list[str]:
        p = list(prefix)
        for c in reversed(self.calls):
            if c[: len(p)] == p:
                return c
        raise AssertionError(f"no call {prefix}")

    @staticmethod
    def _opt(args: list[str], name: str):
        return args[args.index(name) + 1]

    # -- the run_aws stand-in ---------------------------------------
    def __call__(self, config, args):
        a = list(args)
        self.calls.append(a)

        if a[:2] == ["logs", "create-log-group"]:
            name = self._opt(a, "--log-group-name")
            if name in self.log_groups:
                return (254, "", "An error occurred (ResourceAlreadyExistsException)")
            self.log_groups.add(name)
            return (0, "{}", "")
        if a[:2] == ["logs", "put-retention-policy"]:
            return (0, "{}", "")

        if a[:2] == ["batch", "describe-compute-environments"]:
            envs = self.compute_envs
            if "--compute-environments" in a:
                want = self._opt(a, "--compute-environments")
                envs = [e for e in envs if e["computeEnvironmentName"] == want]
            # stamp the current async status on the way out
            status = self._next_ce_status() if envs else None
            envs = [{**e, "status": status,
                     **({"statusReason": self._ce_reason} if self._ce_reason else {})}
                    for e in envs]
            return (0, json.dumps({"computeEnvironments": envs}), "")
        if a[:2] == ["batch", "create-compute-environment"]:
            self.compute_envs.append({
                "computeEnvironmentName": self._opt(a, "--compute-environment-name"),
                "type": "MANAGED", "state": "ENABLED",
                "computeResources": json.loads(self._opt(a, "--compute-resources")),
            })
            return (0, "{}", "")
        if a[:2] == ["batch", "update-compute-environment"]:
            want = self._opt(a, "--compute-environment")
            patch = json.loads(self._opt(a, "--compute-resources"))
            for e in self.compute_envs:
                if e["computeEnvironmentName"] == want:
                    e["computeResources"].update(patch)
            return (0, "{}", "")

        if a[:2] == ["batch", "describe-job-queues"]:
            qs = self.job_queues
            if "--job-queues" in a:
                want = self._opt(a, "--job-queues")
                qs = [q for q in qs if q["jobQueueName"] == want]
            status = self._next_q_status() if qs else None
            qs = [{**q, "status": status,
                   **({"statusReason": self._q_reason} if self._q_reason else {})}
                  for q in qs]
            return (0, json.dumps({"jobQueues": qs}), "")
        if a[:2] == ["batch", "create-job-queue"]:
            self.job_queues.append({
                "jobQueueName": self._opt(a, "--job-queue-name"),
                "state": "ENABLED",
                "priority": int(self._opt(a, "--priority")),
                "computeEnvironmentOrder": json.loads(
                    self._opt(a, "--compute-environment-order")),
            })
            return (0, "{}", "")
        if a[:2] == ["batch", "update-job-queue"]:
            want = self._opt(a, "--job-queue")
            for q in self.job_queues:
                if q["jobQueueName"] == want:
                    q["priority"] = int(self._opt(a, "--priority"))
                    q["state"] = "ENABLED"
                    q["computeEnvironmentOrder"] = json.loads(
                        self._opt(a, "--compute-environment-order"))
            return (0, "{}", "")

        if a[:2] == ["batch", "describe-job-definitions"]:
            defs = self.job_defs
            if "--job-definition-name" in a:
                want = self._opt(a, "--job-definition-name")
                defs = [d for d in defs if d["jobDefinitionName"] == want]
            return (0, json.dumps({"jobDefinitions": defs}), "")
        if a[:2] == ["batch", "register-job-definition"]:
            name = self._opt(a, "--job-definition-name")
            rev = 1 + max(
                [d["revision"] for d in self.job_defs
                 if d["jobDefinitionName"] == name], default=0)
            self.job_defs.append({
                "jobDefinitionName": name, "revision": rev, "status": "ACTIVE",
                "containerProperties": json.loads(self._opt(a, "--container-properties")),
                "timeout": json.loads(self._opt(a, "--timeout")),
                "retryStrategy": json.loads(self._opt(a, "--retry-strategy")),
            })
            return (0, "{}", "")

        raise AssertionError(f"unexpected AWS call: {a}")

    # -- pre-seed matching resources -------------------------------
    def seed_ready(self):
        self.compute_envs.append({
            "computeEnvironmentName": "cryostack-fargate", "type": "MANAGED",
            "state": "ENABLED", "status": "VALID",
            "computeResources": {"type": "FARGATE", "maxvCpus": 16,
                                 "subnets": SUBNETS, "securityGroupIds": SGS},
        })
        self.job_queues.append({
            "jobQueueName": "cryostack-queue", "state": "ENABLED", "priority": 1,
            "status": "VALID",
            "computeEnvironmentOrder": [
                {"order": 1, "computeEnvironment": "cryostack-fargate"}],
        })
        cp = container_properties_payload(
            model="issm", image=IMAGE, job_role_arn=JOB_ROLE,
            execution_role_arn=EXEC_ROLE, region="us-east-2")
        self.job_defs.append({
            "jobDefinitionName": "cryostack-issm", "revision": 3, "status": "ACTIVE",
            "containerProperties": cp,
            "timeout": {"attemptDurationSeconds": DEFAULT_ISSM_JOB_CONFIG.timeout_seconds},
            "retryStrategy": {"attempts": DEFAULT_ISSM_JOB_CONFIG.attempts},
        })
        self.log_groups.add("/cryostack/batch/issm")


@pytest.fixture
def aws(monkeypatch):
    fake = FakeAWS()
    monkeypatch.setattr(bp, "run_aws", fake)
    monkeypatch.setattr(batch_mod, "run_aws", fake)
    return fake


_SLEPT: list[float] = []


def _provision(**over):
    _SLEPT.clear()
    kw = dict(
        subnets=SUBNETS, security_groups=SGS, job_role_arn=JOB_ROLE,
        execution_role_arn=EXEC_ROLE, issm_image=IMAGE,
        # deterministic, no real waiting: 6 describe attempts per resource
        ready_interval=0.01, ready_timeout=0.05, sleep=_SLEPT.append,
    )
    kw.update(over)
    return bp.ensure_batch_resources(CONFIG, **kw)


# ── fresh account: everything is created ────────────────────────────────
def test_fresh_account_creates_all_resources(aws):
    result = _provision()

    assert set(result.created) == {
        "compute_environment", "job_queue", "issm_job_definition"}
    assert result.updated == [] and result.reused == []
    assert result.log_groups == ["/cryostack/batch/issm"]

    assert aws.count("batch", "create-compute-environment") == 1
    assert aws.count("batch", "create-job-queue") == 1
    assert aws.count("batch", "register-job-definition") == 1
    assert aws.count("batch", "update-compute-environment") == 0

    # describe happened before every create
    kinds = [c[1] for c in aws.calls if c[0] == "batch"]
    assert kinds.index("describe-compute-environments") < kinds.index("create-compute-environment")
    assert kinds.index("describe-job-queues") < kinds.index("create-job-queue")

    # final discovery reflects the new resources
    assert result.resources.compute_environment == "cryostack-fargate"
    assert result.resources.job_queue == "cryostack-queue"
    assert result.resources.issm_job_definition == "cryostack-issm"


def test_compute_environment_request_is_fargate_and_bounded(aws):
    _provision()
    call = aws.last("batch", "create-compute-environment")
    cr = json.loads(call[call.index("--compute-resources") + 1])
    assert call[call.index("--type") + 1] == "MANAGED"
    assert cr["type"] == "FARGATE"
    assert cr["maxvCpus"] == 16
    assert "minvCpus" not in cr and "desiredvCpus" not in cr and "instanceTypes" not in cr


def test_job_definition_request_has_logs_roles_timeout_storage(aws):
    _provision()
    call = aws.last("batch", "register-job-definition")
    assert call[call.index("--platform-capabilities") + 1] == "FARGATE"
    cp = json.loads(call[call.index("--container-properties") + 1])
    timeout = json.loads(call[call.index("--timeout") + 1])
    retry = json.loads(call[call.index("--retry-strategy") + 1])
    assert cp["logConfiguration"]["logDriver"] == "awslogs"
    assert cp["jobRoleArn"] == JOB_ROLE
    assert cp["executionRoleArn"] == EXEC_ROLE
    assert cp["ephemeralStorage"]["sizeInGiB"] == 50
    assert timeout["attemptDurationSeconds"] == 3600
    assert retry["attempts"] == 1
    # log group created up front + retention pinned
    assert aws.count("logs", "create-log-group") == 1
    assert aws.count("logs", "put-retention-policy") == 1


# ── idempotency ────────────────────────────────────────────────────────
def test_second_run_reuses_everything(aws):
    aws.seed_ready()
    result = _provision()

    assert set(result.reused) == {
        "compute_environment", "job_queue", "issm_job_definition"}
    assert result.created == [] and result.updated == []
    assert aws.count("batch", "create-compute-environment") == 0
    assert aws.count("batch", "create-job-queue") == 0
    assert aws.count("batch", "register-job-definition") == 0
    assert aws.count("batch", "update-compute-environment") == 0


def test_maxvcpus_drift_triggers_update_not_recreate(aws):
    aws.seed_ready()
    aws.compute_envs[0]["computeResources"]["maxvCpus"] = 8       # drift

    result = _provision()
    assert "compute_environment" in result.updated
    assert aws.count("batch", "update-compute-environment") == 1
    assert aws.count("batch", "create-compute-environment") == 0
    assert aws.compute_envs[0]["computeResources"]["maxvCpus"] == 16


def test_image_drift_registers_a_new_job_definition_revision(aws):
    aws.seed_ready()
    aws.job_defs[0]["containerProperties"]["image"] = "old/image:v0"

    result = _provision()
    assert "issm_job_definition" in result.created
    assert aws.count("batch", "register-job-definition") == 1
    assert aws.job_defs[-1]["revision"] == 4                      # seeded rev was 3


def test_existing_log_group_is_tolerated(aws):
    aws.seed_ready()                                              # log group present
    aws.job_defs[0]["containerProperties"]["image"] = "force/rewrite:v0"

    result = _provision()                                        # touches the log group
    assert aws.count("logs", "put-retention-policy") == 1        # still pinned
    assert "issm_job_definition" in result.created


# ── degraded inputs never make an AWS mess ─────────────────────────────
def test_no_subnets_skips_batch_entirely(aws):
    result = _provision(subnets=[])
    assert any("subnet" in s for s in result.skipped)
    assert aws.count("batch", "create-compute-environment") == 0
    assert aws.count("batch", "register-job-definition") == 0
    assert result.resources is not None


def test_missing_roles_skips_only_the_job_definition(aws):
    result = _provision(job_role_arn="")
    assert set(result.created) == {"compute_environment", "job_queue"}
    assert any("issm_job_definition" in s for s in result.skipped)
    assert aws.count("batch", "register-job-definition") == 0


def test_missing_image_skips_only_the_job_definition(aws):
    result = _provision(issm_image=None)
    assert set(result.created) == {"compute_environment", "job_queue"}
    assert any("issm_job_definition" in s for s in result.skipped)


# -- Icepack Cloud Execution checkpoint -----------------------------------
ICEPACK_IMAGE = "123456789012.dkr.ecr.us-east-2.amazonaws.com/cryostack-icepack:tested"


def test_include_icepack_provisions_both_job_definitions_and_log_groups(aws):
    result = _provision(include_icepack=True, icepack_image=ICEPACK_IMAGE)
    assert set(result.created) == {
        "compute_environment", "job_queue",
        "issm_job_definition", "icepack_job_definition"}
    assert set(result.log_groups) == {
        "/cryostack/batch/issm", "/cryostack/batch/icepack"}
    assert aws.count("batch", "register-job-definition") == 2
    images = {jd["containerProperties"]["image"] for jd in aws.job_defs}
    assert images == {IMAGE, ICEPACK_IMAGE}


def test_include_icepack_is_idempotent_on_a_second_prepare(aws):
    first = _provision(include_icepack=True, icepack_image=ICEPACK_IMAGE)
    assert "icepack_job_definition" in first.created

    second = _provision(include_icepack=True, icepack_image=ICEPACK_IMAGE)
    assert "issm_job_definition" in second.reused
    assert "icepack_job_definition" in second.reused
    assert aws.count("batch", "register-job-definition") == 2   # no new revisions


def test_include_icepack_missing_image_skips_only_icepack(aws):
    """ISSM must never be blocked by Icepack's delivery being unready."""
    result = _provision(include_icepack=True, icepack_image=None)
    assert "issm_job_definition" in result.created
    assert any("icepack_job_definition" in s for s in result.skipped)
    assert aws.count("batch", "register-job-definition") == 1


# -- ICESEE Cloud Execution checkpoint ------------------------------------
# ICESEE's tested image + local runtime verification (2026-09-08) proved
# `with-icesee` + `mpirun --allow-run-as-root -np 1 ...` runs the Lorenz-96
# example end-to-end; this provisioning support follows the exact same
# idempotent describe-before-create pattern already proven for Icepack
# above, using ICESEE's own env-var-driven command instead of the shared
# ISSM/Icepack ``job_command``.
ICESEE_IMAGE = "123456789012.dkr.ecr.us-east-2.amazonaws.com/cryostack-icesee:tested"
ICESEE_COMMAND = ["bash", "-c", "echo icesee-runner"]


def test_include_icesee_provisions_its_own_job_definition_and_log_group(aws):
    result = _provision(include_icesee=True, icesee_image=ICESEE_IMAGE,
                         icesee_command=ICESEE_COMMAND)
    assert set(result.created) == {
        "compute_environment", "job_queue",
        "issm_job_definition", "icesee_job_definition"}
    assert set(result.log_groups) == {
        "/cryostack/batch/issm", "/cryostack/batch/icesee"}
    assert aws.count("batch", "register-job-definition") == 2
    images = {jd["containerProperties"]["image"] for jd in aws.job_defs}
    assert images == {IMAGE, ICESEE_IMAGE}
    icesee_jd = next(
        jd for jd in aws.job_defs if jd["jobDefinitionName"] == "cryostack-icesee")
    assert icesee_jd["containerProperties"]["command"] == ICESEE_COMMAND


def test_include_icesee_is_idempotent_on_a_second_prepare(aws):
    first = _provision(include_icesee=True, icesee_image=ICESEE_IMAGE,
                        icesee_command=ICESEE_COMMAND)
    assert "icesee_job_definition" in first.created

    second = _provision(include_icesee=True, icesee_image=ICESEE_IMAGE,
                         icesee_command=ICESEE_COMMAND)
    assert "issm_job_definition" in second.reused
    assert "icesee_job_definition" in second.reused
    assert aws.count("batch", "register-job-definition") == 2   # no new revisions


def test_include_icesee_missing_image_skips_only_icesee(aws):
    """ISSM must never be blocked by ICESEE's delivery being unready."""
    result = _provision(include_icesee=True, icesee_image=None,
                         icesee_command=ICESEE_COMMAND)
    assert "issm_job_definition" in result.created
    assert any("icesee_job_definition" in s for s in result.skipped)
    assert aws.count("batch", "register-job-definition") == 1


def test_include_icesee_and_icepack_together_are_independent(aws):
    """Icepack and ICESEE can both be requested at once; neither blocks the
    other, and each gets its own job definition/log group/command."""
    result = _provision(
        include_icepack=True, icepack_image=ICEPACK_IMAGE,
        include_icesee=True, icesee_image=ICESEE_IMAGE, icesee_command=ICESEE_COMMAND,
    )
    assert set(result.created) == {
        "compute_environment", "job_queue", "issm_job_definition",
        "icepack_job_definition", "icesee_job_definition"}
    assert aws.count("batch", "register-job-definition") == 3
    icepack_jd = next(
        jd for jd in aws.job_defs if jd["jobDefinitionName"] == "cryostack-icepack")
    icesee_jd = next(
        jd for jd in aws.job_defs if jd["jobDefinitionName"] == "cryostack-icesee")
    assert icepack_jd["containerProperties"]["command"] == ["cryostack-run"]
    assert icesee_jd["containerProperties"]["command"] == ICESEE_COMMAND


# ── driver end to end: digest pin, one revision, idempotent second run ──
def test_prepare_batch_pins_digest_and_makes_exactly_one_revision(aws, monkeypatch):
    from types import SimpleNamespace

    from cryostack_src.cloud.drivers.aws import driver as driver_mod
    from cryostack_src.cloud.drivers.aws.driver import AWSDriver
    from cryostack_src.cloud.drivers.aws.registry_delivery import ECRImageDelivery

    immutable = f"{IMAGE.rsplit(':', 1)[0]}@sha256:cafebabe"
    delivery = ECRImageDelivery(
        model="issm", repository="cryostack-issm",
        repository_uri=IMAGE.rsplit(":", 1)[0], tag="tested",
        source_reference="bkyanjo/icesee-combined:v1.0.0",
        source_digest="sha256:a727f60a", destination_digest="sha256:cafebabe",
        immutable_reference=immutable, verified=True, reused=True)
    monkeypatch.setattr(driver_mod, "mirror_tested_image",
                        lambda config, **kw: delivery)

    net = SimpleNamespace(subnet_ids=SUBNETS, security_group_ids=SGS)
    iam = SimpleNamespace(job_role=JOB_ROLE, ecs_execution_role=EXEC_ROLE)
    driver = AWSDriver(region="us-east-2")

    first = driver.prepare_batch(network=net, iam=iam)
    assert "issm_job_definition" in first.created
    assert aws.job_defs[-1]["containerProperties"]["image"] == immutable
    assert "@sha256:" in aws.job_defs[-1]["containerProperties"]["image"]
    assert first.image_delivery.verified is True

    second = driver.prepare_batch(network=net, iam=iam)
    assert "issm_job_definition" in second.reused
    assert aws.count("batch", "register-job-definition") == 1     # no new revision


# ══════════════════════════════════════════════════════════════════════════
# Batch resource readiness polling (the CreateJobQueue-before-CE-VALID fix)
# ══════════════════════════════════════════════════════════════════════════
from cryostack_src.cloud.drivers.aws.batch_provision import (  # noqa: E402
    BatchResourceNotReady,
    _poll_batch_status,
)


def _seq(*statuses):
    """A describe() that yields one status dict per call, last one sticks."""
    items = list(statuses)

    def describe():
        s = items[0] if len(items) == 1 else items.pop(0)
        return None if s is None else {"state": "ENABLED", "status": s,
                                       "statusReason": f"{s} reason"}
    return describe


# ── the poll helper in isolation ───────────────────────────────────────
def test_poll_returns_immediately_when_already_valid():
    slept = []
    res = _poll_batch_status(_seq("VALID"), what="ce", interval=1, timeout=10,
                             sleep=slept.append)
    assert res["status"] == "VALID" and slept == []


def test_poll_waits_through_creating_then_valid():
    slept = []
    res = _poll_batch_status(_seq("CREATING", "CREATING", "VALID"),
                             what="ce", interval=5, timeout=60, sleep=slept.append)
    assert res["status"] == "VALID" and slept == [5, 5]


def test_poll_waits_through_updating_then_valid():
    slept = []
    res = _poll_batch_status(_seq("UPDATING", "VALID"),
                             what="ce", interval=3, timeout=30, sleep=slept.append)
    assert res["status"] == "VALID" and slept == [3]


def test_poll_raises_on_invalid_with_the_reason():
    with pytest.raises(BatchResourceNotReady) as ei:
        _poll_batch_status(_seq("CREATING", "INVALID"), what="compute environment",
                           interval=1, timeout=10, sleep=lambda _s: None)
    assert "INVALID" in str(ei.value) and "INVALID reason" in str(ei.value)


def test_poll_times_out_with_the_last_state():
    with pytest.raises(BatchResourceNotReady) as ei:
        _poll_batch_status(_seq("CREATING"), what="job queue cryostack-queue",
                           interval=1, timeout=3, sleep=lambda _s: None)
    msg = str(ei.value)
    assert "did not become VALID" in msg and "status='CREATING'" in msg


def test_poll_tolerates_a_transient_describe_failure():
    slept = []
    res = _poll_batch_status(_seq(None, "CREATING", "VALID"),
                             what="ce", interval=2, timeout=20, sleep=slept.append)
    assert res["status"] == "VALID" and slept == [2, 2]


# ── ensure_compute_environment / ensure_job_queue ──────────────────────
def test_ce_already_valid_is_reused_without_waiting(aws):
    aws.seed_ready()
    out = bp.ensure_compute_environment(
        CONFIG, subnets=SUBNETS, security_groups=SGS,
        ready_interval=0.01, ready_timeout=0.05, sleep=_SLEPT.append)
    _SLEPT.clear()
    assert out == "reused" and _SLEPT == []


def test_ce_creating_then_valid_on_create(aws):
    aws._ce_seq = ["CREATING", "VALID"]
    out = bp.ensure_compute_environment(
        CONFIG, subnets=SUBNETS, security_groups=SGS,
        ready_interval=0.01, ready_timeout=1.0, sleep=lambda _s: None)
    assert out == "created"
    assert aws.count("batch", "create-compute-environment") == 1


def test_ce_invalid_fails_before_the_queue_is_touched(aws):
    aws._ce_seq = ["CREATING", "INVALID"]
    aws._ce_reason = "CLIENT_ERROR: bad subnet"
    with pytest.raises(BatchResourceNotReady) as ei:
        _provision(sleep=lambda _s: None)
    assert "CLIENT_ERROR" in str(ei.value)
    assert aws.count("batch", "create-job-queue") == 0        # never got there


def test_ce_timeout_fails_clearly(aws):
    aws._ce_seq = ["CREATING"]                                # never valid
    with pytest.raises(BatchResourceNotReady) as ei:
        _provision(sleep=lambda _s: None)
    assert "did not become VALID" in str(ei.value)
    assert aws.count("batch", "create-job-queue") == 0


def test_queue_creating_then_valid_on_create(aws):
    aws._q_seq = ["CREATING", "CREATING", "VALID"]
    result = _provision()
    assert "job_queue" in result.created
    assert aws.count("batch", "create-job-queue") == 1


def test_queue_invalid_fails_with_reason(aws):
    aws._q_seq = ["CREATING", "INVALID"]
    aws._q_reason = "COMPUTE_ENVIRONMENT_ERROR"
    with pytest.raises(BatchResourceNotReady) as ei:
        _provision(sleep=lambda _s: None)
    assert "COMPUTE_ENVIRONMENT_ERROR" in str(ei.value)


def test_queue_timeout_fails_clearly(aws):
    aws._q_seq = ["CREATING"]
    with pytest.raises(BatchResourceNotReady) as ei:
        _provision(sleep=lambda _s: None)
    assert "job queue cryostack-queue did not become VALID" in str(ei.value)


# ── the exact live partial state: CE VALID, no queue, no job def ───────
def _seed_live_partial(aws):
    """account 713938953301 state after the first failed bootstrap:
    S3 + ECR exist (elsewhere); CE VALID; queue + job definition absent."""
    aws.compute_envs.append({
        "computeEnvironmentName": "cryostack-fargate", "type": "MANAGED",
        "state": "ENABLED", "status": "VALID",
        "statusReason": "ComputeEnvironment Healthy",
        "computeResources": {"type": "FARGATE", "maxvCpus": 16,
                             "subnets": SUBNETS, "securityGroupIds": SGS},
    })
    # no job_queues, no job_defs, no log group


def test_rerun_on_the_live_partial_state_completes_only_whats_missing(aws):
    _seed_live_partial(aws)
    result = _provision()

    # CE is reused (VALID, no drift) -- not recreated, not updated
    assert "compute_environment" in result.reused
    assert aws.count("batch", "create-compute-environment") == 0
    assert aws.count("batch", "update-compute-environment") == 0

    # only the missing queue + job definition are created
    assert "job_queue" in result.created
    assert "issm_job_definition" in result.created
    assert aws.count("batch", "create-job-queue") == 1
    assert aws.count("batch", "register-job-definition") == 1

    # describe-CE happened before create-job-queue (readiness gate)
    kinds = [c[1] for c in aws.calls if c[0] == "batch"]
    assert kinds.index("describe-compute-environments") < kinds.index("create-job-queue")


def test_second_rerun_after_the_fix_creates_nothing(aws):
    _seed_live_partial(aws)
    _provision()                                              # completes the stack
    aws.calls.clear()
    result = _provision()                                     # run again

    assert result.created == [] and result.updated == []
    assert set(result.reused) == {
        "compute_environment", "job_queue", "issm_job_definition"}
    assert aws.count("batch", "create-job-queue") == 0
    assert aws.count("batch", "create-compute-environment") == 0
    assert aws.count("batch", "register-job-definition") == 0


def test_ce_update_waits_through_updating_then_valid(aws):
    aws.seed_ready()
    aws.compute_envs[0]["computeResources"]["maxvCpus"] = 8       # force an update
    aws._ce_seq = ["VALID", "UPDATING", "UPDATING", "VALID"]      # describe(pre) then poll
    result = _provision()
    assert "compute_environment" in result.updated
    assert aws.count("batch", "update-compute-environment") == 1
    assert "job_queue" in result.reused                          # queue was already VALID
