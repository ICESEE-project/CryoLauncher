"""ICESEE Cloud tab now submits/polls/terminates through the hardened
CloudBridge adapter (icesee_jupyter_book/core/cloud_bridge_adapter.py)
instead of calling core/cloud_runner.py's functions directly -- Step 4 of
the ICESEE<->CryoLauncher cloud convergence
(overnight/AUDIT_icesee_cloud_convergence.md). No real AWS CLI is invoked:
every test patches the lowest real boundary
(cryostack_src.cloud.legacy.aws_batch's ``subprocess``), the same pattern
cryostack_src/cloud/tests/test_aws_batch_legacy_credentials.py uses.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_GW = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"


def test_gateway_uses_the_cloud_bridge_adapter_not_the_legacy_functions_directly():
    src = _GW.read_text()
    assert "from icesee_jupyter_book.core.cloud_bridge_adapter import" in src
    assert "build_icesee_cloud_bridge(" in src
    assert "submit_icesee_cloud_run(" in src
    assert "icesee_cloud_status(" in src
    assert "icesee_cloud_terminate(" in src
    # the legacy entry points are no longer imported into the gateway --
    # they still exist and are exercised THROUGH the adapter
    assert "from icesee_jupyter_book.core.cloud_runner import" not in src
    assert "cloud_terminate_btn" in src   # a genuinely new capability


class _FakeCompleted:
    def __init__(self, stdout):
        self.returncode, self.stdout, self.stderr = 0, stdout, ""


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


def _freevar(fn, name):
    idx = fn.__code__.co_freevars.index(name)
    return fn.__closure__[idx].cell_contents


def _select_cloud_mode(page):
    mode_tabs = None

    def walk(w):
        nonlocal mode_tabs
        if isinstance(w, W.Tab) and mode_tabs is None:
            mode_tabs = w
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    mode_tabs.selected_index = 2   # Cloud
    return mode_tabs


def test_cloud_submit_reaches_batch_submit_job_with_the_documented_env_vars(
    monkeypatch, tmp_path, capsys,
):
    import cryostack_src.cloud.legacy.aws_batch as legacy_batch

    calls = []

    class _FakeSubprocess:
        @staticmethod
        def run(argv, **kwargs):
            calls.append(argv)
            if "get-caller-identity" in argv:
                return _FakeCompleted('{"Account": "1"}')
            if "submit-job" in argv:
                return _FakeCompleted(json.dumps({"jobId": "job-xyz"}))
            return _FakeCompleted("")

    monkeypatch.setattr(legacy_batch, "subprocess", _FakeSubprocess)

    page = _build_gateway(monkeypatch, tmp_path, user="cloud-submit-user")
    _select_cloud_mode(page)
    submit_btn = _find_button(page, "Submit")
    assert submit_btn is not None
    click_handler = submit_btn._click_handlers.callbacks[0]
    handler = _freevar(click_handler, "run_example_cloud_submit")

    aws_region = _freevar(handler, "aws_region")
    cloud_bucket = _freevar(handler, "cloud_bucket")
    batch_job_queue = _freevar(handler, "batch_job_queue")
    batch_job_def = _freevar(handler, "batch_job_def")
    aws_region.value = "us-east-2"
    cloud_bucket.value = "s3://bucket/runs"
    batch_job_queue.value = "q"
    batch_job_def.value = "jd"

    capsys.readouterr()
    handler()
    printed = capsys.readouterr().out
    assert "[cloud][ERROR]" not in printed

    submit_call = next(c for c in calls if "submit-job" in c)
    overrides = json.loads(submit_call[submit_call.index("--container-overrides") + 1])
    env = {e["name"]: e["value"] for e in overrides["environment"]}
    assert env["ICESEE_S3_RUN"].startswith("s3://bucket/runs/")
    assert "ICESEE_EXAMPLE" in env and "ICESEE_RUN_SCRIPT" in env

    STATUS = _freevar(handler, "STATUS")
    assert STATUS["batch_job_id"] == "job-xyz"
    assert STATUS["s3_run"] == env["ICESEE_S3_RUN"]
    assert Path(STATUS["local_run_dir"]).is_dir()
    assert (Path(STATUS["local_run_dir"]) / ".cryostack-run.json").is_file()


def test_cloud_status_and_terminate_flow_through_the_hardened_driver(
    monkeypatch, tmp_path, capsys,
):
    import cryostack_src.cloud.legacy.aws_batch as legacy_batch

    calls = []

    class _FakeSubprocess:
        @staticmethod
        def run(argv, **kwargs):
            calls.append(argv)
            if "describe-jobs" in argv:
                return _FakeCompleted(json.dumps(
                    {"jobs": [{"status": "RUNNING", "statusReason": ""}]}))
            return _FakeCompleted("")

    monkeypatch.setattr(legacy_batch, "subprocess", _FakeSubprocess)

    page = _build_gateway(monkeypatch, tmp_path, user="cloud-status-user")
    _select_cloud_mode(page)

    status_btn = _find_button(page, "Check status", icon="search")
    status_click = status_btn._click_handlers.callbacks[0]
    status_handler = _freevar(status_click, "run_example_cloud_status")
    STATUS = _freevar(status_handler, "STATUS")
    STATUS["batch_job_id"] = "job-123"

    capsys.readouterr()
    status_handler()
    printed = capsys.readouterr().out
    assert "RUNNING" in printed
    assert any("describe-jobs" in c for c in calls)

    terminate_btn = _find_button(page, "Terminate cloud job")
    assert terminate_btn is not None
    terminate_click = terminate_btn._click_handlers.callbacks[0]
    terminate_handler = _freevar(terminate_click, "run_example_cloud_terminate")
    capsys.readouterr()
    terminate_handler()
    printed = capsys.readouterr().out
    assert "[cloud][ERROR]" not in printed
    assert any("cancel-job" in c or "terminate-job" in c for c in calls)


def test_cloud_terminate_with_no_job_id_yet_is_a_clean_noop(monkeypatch, tmp_path, capsys):
    page = _build_gateway(monkeypatch, tmp_path, user="cloud-terminate-noop-user")
    _select_cloud_mode(page)
    terminate_btn = _find_button(page, "Terminate cloud job")
    click_handler = terminate_btn._click_handlers.callbacks[0]
    handler = _freevar(click_handler, "run_example_cloud_terminate")

    capsys.readouterr()
    handler()
    printed = capsys.readouterr().out
    assert "No Batch job id yet" in printed
