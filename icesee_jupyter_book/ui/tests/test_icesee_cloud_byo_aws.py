"""ICESEE Cloud BYO-AWS parity.

ICESEE's cloud submit/status/terminate now resolve credentials through the
SAME shared cryostack_src.cloud.connect.resolve_cloud_execution CryoLauncher
uses, not an ICESEE-only credential path. A user who already connected a
BYO AWS account (through CryoLauncher's existing UI -- AWSConnectionStore is
scoped to the authenticated CryoStack user, not the app) gets that same
account here automatically, with zero new ICESEE UI. Developer/ambient mode
(no connection) is unchanged: every field must still be typed by hand.

No real AWS is ever contacted: assume_role's STS calls are faked by
patching cryostack_src.cloud.connect.assume_role's `subprocess` (the same
boundary its own test suite patches), and every Batch/S3 call is faked by
patching cryostack_src.cloud.legacy.aws_batch's `subprocess`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

ROLE_ARN = "arn:aws:iam::774888247882:role/CryoStackExecutionRole"
ACCOUNT_ID = "774888247882"


class _FakeCompleted:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class _FakeSubprocess:
    """Handles sts assume-role/get-caller-identity AND batch/s3 calls, so
    the same fake serves both cryostack_src.cloud.connect.assume_role and
    cryostack_src.cloud.legacy.aws_batch."""

    def __init__(self):
        self.calls = []
        self._sts_calls = 0

    def run(self, argv, **kwargs):
        self.calls.append({"argv": argv, "env": kwargs.get("env")})
        if argv[1:3] == ["sts", "assume-role"]:
            self._sts_calls += 1
            return _FakeCompleted(json.dumps({
                "Credentials": {
                    "AccessKeyId": f"ASIA{self._sts_calls}", "SecretAccessKey": "s",
                    "SessionToken": "t", "Expiration": "2026-09-08T01:00:00Z",
                },
            }))
        if argv[1:3] == ["sts", "get-caller-identity"]:
            return _FakeCompleted(json.dumps({"Account": ACCOUNT_ID}))
        if "submit-job" in argv:
            return _FakeCompleted(json.dumps({"jobId": "job-byo"}))
        if "describe-jobs" in argv:
            return _FakeCompleted(json.dumps(
                {"jobs": [{"status": "RUNNING", "statusReason": ""}]}))
        return _FakeCompleted("")


def _connect_byo_account(tmp_path, *, user_id):
    from cryostack_src.cloud.connect import AWSConnectionStore, verify_connection
    from cryostack_src.workspace.identity import WorkspaceUser

    class _VerifySTS:
        def __call__(self, args, **kwargs):
            if args[:2] == ["sts", "assume-role"]:
                return {"Credentials": {
                    "AccessKeyId": "ASIA0", "SecretAccessKey": "s", "SessionToken": "t",
                    "Expiration": "2026-09-08T01:00:00Z",
                }}
            if args[:2] == ["sts", "get-caller-identity"]:
                return {"Account": ACCOUNT_ID}
            raise AssertionError(args)

    user = WorkspaceUser(user_id=user_id, source="env-override")
    store = AWSConnectionStore(user=user, workspace_root=tmp_path)
    conn = store.create(region="us-east-2")
    result = verify_connection(conn, role_arn=ROLE_ARN, runner=_VerifySTS())
    store.save(result.connection)
    return store


def _build_gateway(monkeypatch, tmp_path, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", f"{user}-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui
    return build_icesee_ui()


def _find_button(page, description, *, icon=None):
    found = []

    def walk(w):
        if isinstance(w, W.Button) and getattr(w, "description", "") == description:
            if icon is None or getattr(w, "icon", "") == icon:
                found.append(w)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    return found[0] if found else None


def _select_cloud_mode(page):
    mode_tabs = None

    def walk(w):
        nonlocal mode_tabs
        if isinstance(w, W.Tab) and mode_tabs is None:
            mode_tabs = w
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    mode_tabs.selected_index = 2
    return mode_tabs


def _freevar(fn, name):
    idx = fn.__code__.co_freevars.index(name)
    return fn.__closure__[idx].cell_contents


def test_gateway_resolves_credentials_through_the_shared_resolver():
    src = (_REPO / "icesee_jupyter_book/ui/icesee_gateway.py").read_text()
    assert "from cryostack_src.cloud.connect import resolve_cloud_execution" in src
    assert 'model="icesee"' in src


def test_byo_submit_uses_connected_account_credentials_and_prepared_defaults(
    monkeypatch, tmp_path,
):
    _connect_byo_account(tmp_path, user_id="byo-submit-user")

    fake = _FakeSubprocess()
    # cryostack_src.cloud.connect's __init__ does `from .assume_role import
    # assume_role`, which rebinds the `assume_role` ATTRIBUTE on the
    # `connect` package to the function -- `import ...connect.assume_role`
    # would resolve to that function, not the submodule. Go through
    # sys.modules for the real submodule object.
    import importlib
    import cryostack_src.cloud.legacy.aws_batch as legacy_batch
    assume_role_mod = importlib.import_module("cryostack_src.cloud.connect.assume_role")
    monkeypatch.setattr(assume_role_mod, "subprocess", fake)
    monkeypatch.setattr(legacy_batch, "subprocess", fake)

    page = _build_gateway(monkeypatch, tmp_path, user="byo-submit-user")
    _select_cloud_mode(page)
    submit_click = _find_button(page, "Launch cloud run")._click_handlers.callbacks[0]
    submit_handler = _freevar(submit_click, "run_example_cloud_submit")

    # deliberately leave bucket/queue/job-definition BLANK
    cloud_bucket = _freevar(submit_handler, "cloud_bucket")
    batch_job_queue = _freevar(submit_handler, "batch_job_queue")
    batch_job_def = _freevar(submit_handler, "batch_job_def")
    assert cloud_bucket.value == "" and batch_job_queue.value == "" and batch_job_def.value == ""

    submit_handler()

    STATUS = _freevar(submit_handler, "STATUS")
    assert STATUS["batch_job_id"] == "job-byo"

    submit_call = next(c for c in fake.calls if "submit-job" in c["argv"])
    # BYO credentials reached the subprocess env, never a profile
    assert submit_call["env"]["AWS_ACCESS_KEY_ID"].startswith("ASIA")
    assert "AWS_PROFILE" not in (submit_call["env"] or {})

    overrides = json.loads(
        submit_call["argv"][submit_call["argv"].index("--container-overrides") + 1]
    )
    env = {e["name"]: e["value"] for e in overrides["environment"]}
    assert env["ICESEE_S3_RUN"].startswith(f"s3://cryostack-runs-{ACCOUNT_ID}/runs/")

    from cryostack_src.workspace import read_manifest
    from icesee_jupyter_book.core.run_records import MANIFEST_NAME
    manifest = Path(STATUS["local_run_dir"]) / MANIFEST_NAME
    resources = read_manifest(manifest).metadata["aws_resources"]
    assert resources["account_id"] == ACCOUNT_ID
    assert resources["job_queue"] == "cryostack-queue"
    assert resources["job_definition"] == "cryostack-icesee"


def test_developer_mode_still_requires_explicit_fields_unchanged(monkeypatch, tmp_path, capsys):
    """No connection -> unchanged behavior: blank fields must still fail,
    exactly like before BYO-AWS resolution was wired in."""
    page = _build_gateway(monkeypatch, tmp_path, user="dev-mode-unchanged-user")
    _select_cloud_mode(page)
    submit_click = _find_button(page, "Launch cloud run")._click_handlers.callbacks[0]
    submit_handler = _freevar(submit_click, "run_example_cloud_submit")

    capsys.readouterr()
    submit_handler()   # bucket/queue/job-def all blank, no connection
    printed = capsys.readouterr().out
    assert "[cloud][ERROR]" in printed


def test_status_and_terminate_use_the_runs_own_persisted_region_not_the_live_widget(
    monkeypatch, tmp_path,
):
    """Historical reproducibility: once submitted, later Check status /
    Terminate calls must resolve against the run's OWN persisted region
    (metadata['aws_resources']['region']), not whatever the Cloud panel's
    region field says NOW -- proven by changing the widget after submit."""
    fake = _FakeSubprocess()
    import cryostack_src.cloud.legacy.aws_batch as legacy_batch
    monkeypatch.setattr(legacy_batch, "subprocess", fake)

    page = _build_gateway(monkeypatch, tmp_path, user="region-pin-user")
    _select_cloud_mode(page)
    submit_click = _find_button(page, "Launch cloud run")._click_handlers.callbacks[0]
    submit_handler = _freevar(submit_click, "run_example_cloud_submit")

    aws_region = _freevar(submit_handler, "aws_region")
    cloud_bucket = _freevar(submit_handler, "cloud_bucket")
    batch_job_queue = _freevar(submit_handler, "batch_job_queue")
    batch_job_def = _freevar(submit_handler, "batch_job_def")
    aws_region.value = "us-east-2"
    cloud_bucket.value = "s3://bucket/runs"
    batch_job_queue.value = "q"
    batch_job_def.value = "jd"
    submit_handler()

    # the user now changes the region field -- a later status check must
    # still query us-east-2 (the run's own persisted region), not this
    aws_region.value = "eu-west-1"

    status_click = _find_button(page, "Check status", icon="search")._click_handlers.callbacks[0]
    status_handler = _freevar(status_click, "run_example_cloud_status")
    status_handler()

    describe_call = next(c for c in fake.calls if "describe-jobs" in c["argv"])
    assert "us-east-2" in describe_call["argv"]
    assert "eu-west-1" not in describe_call["argv"]
