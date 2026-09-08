"""ICESEE Cloud UI parity: the legacy developer-oriented panel
(Region/Profile/S3 prefix/Queue/Job def/Job name/Submit as primary fields)
is gone. ICESEE Cloud mode now uses the SAME shared Cloud Environment
component CryoLauncher uses (build_cloud_environment_card): Provider/
Region, AWS ACCOUNT, INFRASTRUCTURE, Prepare Cloud, RUN ESTIMATE, Review &
Launch, Advanced cloud settings -- with ICESEE's own DA-aware review
content (icesee_jupyter_book/core/cloud_review.py) instead of
CryoLauncher's model/example/run_target schema.

No real AWS is ever contacted in this file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_GW = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"


def _build_gateway(monkeypatch, tmp_path, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", f"{user}-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui
    return build_icesee_ui()


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


def _all_html_values(root):
    out = []

    def walk(w):
        if isinstance(w, W.HTML):
            out.append(w.value or "")
        for c in getattr(w, "children", ()):
            walk(c)

    walk(root)
    return out


def _all_buttons(root):
    out = []

    def walk(w):
        if isinstance(w, W.Button):
            out.append(w)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(root)
    return out


def _all_texts(root):
    out = []

    def walk(w):
        if isinstance(w, W.Text):
            out.append(w)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(root)
    return out


def _find_button(page, description, *, icon=None):
    for b in _all_buttons(page):
        if b.description == description and (icon is None or b.icon == icon):
            return b
    return None


def _freevar(fn, name):
    idx = fn.__code__.co_freevars.index(name)
    return fn.__closure__[idx].cell_contents


# ---------------------------------------------------------------------------
# 1. no legacy primary Profile/S3/Queue/Job-def panel
# ---------------------------------------------------------------------------
def test_icesee_cloud_mode_has_no_legacy_primary_fields_panel(monkeypatch, tmp_path):
    page = _build_gateway(monkeypatch, tmp_path, user="parity-no-legacy")
    mode_tabs = _select_cloud_mode(page)
    cloud_content = mode_tabs.children[2]

    labels = " ".join(_all_html_values(cloud_content))
    for legacy_label in ("S3 prefix:", "Queue:", "Job def:", "Job name:"):
        assert legacy_label not in labels, legacy_label


def test_icesee_cloud_mode_has_no_direct_submit_button(monkeypatch, tmp_path):
    page = _build_gateway(monkeypatch, tmp_path, user="parity-no-submit-btn")
    mode_tabs = _select_cloud_mode(page)
    cloud_content = mode_tabs.children[2]
    buttons = _all_buttons(cloud_content)
    descriptions = [b.description for b in buttons]
    assert "Submit" not in descriptions
    # Launch cloud run (Review & Launch's own action) is the only submit path
    assert "Launch cloud run" in descriptions


# ---------------------------------------------------------------------------
# 2. shared Cloud Environment structure
# ---------------------------------------------------------------------------
def test_icesee_uses_the_shared_cloud_environment_card(monkeypatch, tmp_path):
    src = _GW.read_text()
    assert "build_cloud_environment_card(" in src
    assert "build_aws_connect_callbacks(" in src
    assert "build_cloud_environment_ops(" in src
    # no ICESEE-only imitation of the card
    assert "class CloudEnvironmentWidgets" not in src

    page = _build_gateway(monkeypatch, tmp_path, user="parity-shared-structure")
    mode_tabs = _select_cloud_mode(page)
    cloud_content = mode_tabs.children[2]
    html_blob = "\n".join(_all_html_values(cloud_content))
    assert "AWS ACCOUNT" in html_blob or "Connect" in html_blob
    assert "INFRASTRUCTURE" in html_blob
    buttons = [b.description for b in _all_buttons(cloud_content)]
    assert "Prepare cloud" in buttons
    assert "Review & Launch" in buttons


# ---------------------------------------------------------------------------
# 3. AWS account connection state appears identically to CryoLauncher
# ---------------------------------------------------------------------------
def test_account_connection_widgets_are_the_same_shared_ones_as_cryolauncher(monkeypatch, tmp_path):
    from cryostack_src.frontend.cryolauncher.cloud_environment import CloudEnvironmentWidgets

    page = _build_gateway(monkeypatch, tmp_path, user="parity-account-widgets")
    mode_tabs = _select_cloud_mode(page)
    cloud_content = mode_tabs.children[2]

    click_handler = _find_button(page, "Review & Launch")._click_handlers.callbacks[0]
    icesee_cloud_environment = _freevar(click_handler, "icesee_cloud_environment")
    assert isinstance(icesee_cloud_environment, CloudEnvironmentWidgets)
    assert icesee_cloud_environment.container in _all_html_and_containers(cloud_content) or \
        icesee_cloud_environment.container is cloud_content


def _all_html_and_containers(root):
    seen = []

    def walk(w):
        seen.append(w)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(root)
    return seen


# ---------------------------------------------------------------------------
# 4. Prepare Cloud uses the shared readiness model
# ---------------------------------------------------------------------------
def test_prepare_cloud_uses_the_shared_capabilities_model(monkeypatch, tmp_path):
    prepare_btn = None
    page = _build_gateway(monkeypatch, tmp_path, user="parity-prepare")
    _select_cloud_mode(page)
    prepare_btn = _find_button(page, "Prepare cloud")
    assert prepare_btn is not None
    click_handler = prepare_btn._click_handlers.callbacks[0]
    # the handler is a lambda wrapping icesee_cloud_ops.prepare_cloud(...)
    icesee_cloud_ops = _freevar(click_handler, "icesee_cloud_ops")
    assert hasattr(icesee_cloud_ops, "prepare_cloud")
    assert hasattr(icesee_cloud_ops, "test_connection")


# ---------------------------------------------------------------------------
# 5. overrides live only in Advanced settings
# ---------------------------------------------------------------------------
def test_profile_bucket_queue_jobdef_jobname_live_only_under_advanced(monkeypatch, tmp_path):
    page = _build_gateway(monkeypatch, tmp_path, user="parity-advanced-only")
    mode_tabs = _select_cloud_mode(page)
    cloud_content = mode_tabs.children[2]

    click_handler = _find_button(page, "Review & Launch")._click_handlers.callbacks[0]
    icesee_cloud_environment = _freevar(click_handler, "icesee_cloud_environment")

    advanced = icesee_cloud_environment.advanced
    assert isinstance(advanced, W.Accordion)
    advanced_texts = set(_all_texts(advanced))
    for field in (icesee_cloud_environment.profile, icesee_cloud_environment.s3_prefix,
                  icesee_cloud_environment.job_queue, icesee_cloud_environment.job_definition,
                  icesee_cloud_environment.job_name):
        assert field in advanced_texts, "override field must live under Advanced cloud settings"

    # collapsed by default -- not thrust in front of a normal user
    assert advanced.selected_index is None


# ---------------------------------------------------------------------------
# 6. no direct legacy Submit button (static + structural, belt and braces)
# ---------------------------------------------------------------------------
def test_no_widget_named_cloud_submit_btn_exists_in_source():
    src = _GW.read_text()
    assert "cloud_submit_btn" not in src


# ---------------------------------------------------------------------------
# 7. Review & Launch is the only normal Cloud launch path
# ---------------------------------------------------------------------------
def test_launch_is_blocked_until_review_says_can_launch(monkeypatch, tmp_path, capsys):
    page = _build_gateway(monkeypatch, tmp_path, user="parity-launch-gate")
    _select_cloud_mode(page)

    review_btn = _find_button(page, "Review & Launch")
    launch_btn = _find_button(page, "Launch cloud run")
    assert review_btn is not None and launch_btn is not None

    review_click = review_btn._click_handlers.callbacks[0]
    review_click(None)   # builds + renders the review; ICESEE has no tested
                          # image today, so it must come back blocked
    assert launch_btn.disabled is True

    launch_click = launch_btn._click_handlers.callbacks[0]
    launch_click(None)   # must be a no-op: review.can_launch is False
    STATUS = _freevar(_freevar(launch_click, "run_example_cloud_submit"), "STATUS")
    assert STATUS.get("batch_job_id") is None


def test_launch_succeeds_once_the_review_reports_can_launch(monkeypatch, tmp_path):
    """End-to-end: force a launchable review (as if a tested ICESEE image
    existed) and confirm clicking Launch actually submits -- Review & Launch
    is a real, working path, not just a gate that always blocks."""
    import json

    class _FakeCompleted:
        def __init__(self, stdout):
            self.returncode, self.stdout, self.stderr = 0, stdout, ""

    class _FakeSubprocess:
        @staticmethod
        def run(argv, **kwargs):
            if "submit-job" in argv:
                return _FakeCompleted(json.dumps({"jobId": "job-review-launch"}))
            return _FakeCompleted("")

    import cryostack_src.cloud.legacy.aws_batch as legacy_batch
    monkeypatch.setattr(legacy_batch, "subprocess", _FakeSubprocess)

    page = _build_gateway(monkeypatch, tmp_path, user="parity-launch-success")
    _select_cloud_mode(page)

    review_btn = _find_button(page, "Review & Launch")
    launch_btn = _find_button(page, "Launch cloud run")
    review_click = review_btn._click_handlers.callbacks[0]

    icesee_cloud_environment = _freevar(review_click, "icesee_cloud_environment")
    icesee_cloud_environment.s3_prefix.value = "s3://bucket/runs"
    icesee_cloud_environment.job_queue.value = "q"
    icesee_cloud_environment.job_definition.value = "jd"

    # Force a launchable review the same way the real gate would once a
    # tested ICESEE image is registered. _icesee_build_review() itself
    # cannot be monkeypatched (it is a plain nested function, not a
    # module-level name) -- drive _icesee_review_state directly instead,
    # exactly what _on_icesee_review_click does with whatever
    # _icesee_build_review() returns.
    from cryostack_src.cloud.review import InfrastructureReadiness
    import icesee_jupyter_book.core.cloud_review as cloud_review_mod

    _icesee_review_state = _freevar(review_click, "_icesee_review_state")
    _icesee_review_state["review"] = cloud_review_mod.IceseeCloudReview(
        forecast_model="lorenz96", filter_alg="EnKF", ensemble_size=30,
        execution_mode="cloud", compute_backend="AWS Batch (Fargate)",
        parallel_processes=8, account_id="", region="us-east-1",
        infrastructure=InfrastructureReadiness(True, True, True, True),
        icesee_runtime_ready=True, can_launch=True, blocked_reasons=[],
        digest="fixed",
    )

    launch_click = launch_btn._click_handlers.callbacks[0]
    launch_click(None)

    STATUS = _freevar(_freevar(launch_click, "run_example_cloud_submit"), "STATUS")
    assert STATUS["batch_job_id"] == "job-review-launch"


# ---------------------------------------------------------------------------
# 8. ICESEE DA identity is present in the review
# ---------------------------------------------------------------------------
def test_review_body_contains_da_identity_not_model_example_schema(monkeypatch, tmp_path):
    page = _build_gateway(monkeypatch, tmp_path, user="parity-da-identity")
    _select_cloud_mode(page)

    review_btn = _find_button(page, "Review & Launch")
    review_click = review_btn._click_handlers.callbacks[0]
    icesee_cloud_environment = _freevar(review_click, "icesee_cloud_environment")

    review_click(None)
    body = icesee_cloud_environment.review_body.value
    assert "Forecast model" in body
    assert "Filter" in body
    assert "Ensemble size" in body
    assert "Parallel processes" in body
    # never the CryoLauncher model/example/run_target row labels
    assert "Run target" not in body


# ---------------------------------------------------------------------------
# 9. CryoLauncher Cloud remains unchanged
# ---------------------------------------------------------------------------
def test_cryolauncher_cloud_environment_still_builds_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "parity-cl-unchanged")
    monkeypatch.setenv("USER", "parity-cl-unchanged-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui

    page = build_icesheets_ui()
    assert page is not None
    html_blob = "\n".join(_all_html_values(page))
    assert "Cloud: Not configured" in html_blob
