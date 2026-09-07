"""Cloud Commit 4/5 -- the IceSheets gateway wires the real Cloud path and
leaves the Local / Remote paths untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import ipywidgets as W

_ICESHEETS = _REPO / "icesee_jupyter_book/ui/icesheets_gateway.py"


def test_cloud_placeholder_submission_is_gone():
    src = _ICESHEETS.read_text()
    assert "Placeholder for AWS Batch submission" not in src
    assert "adapt submit_cloud_example for model-only workflows" not in src


def test_cloud_branch_validates_and_preflights_before_submit():
    src = _ICESHEETS.read_text()
    assert "resolve_cloud_config(" in src
    assert "validate_cloud_config(" in src
    assert "cloud_run_preflight(" in src
    assert "_submit_cloud_run(" in src
    # the real bridge submit signature (staged tree + model + bucket)
    assert "staged_source=" in src and "matlab_license_configured=" in src


def test_cloud_run_is_registered_with_backend_aws_and_a_real_job_id():
    src = _ICESHEETS.read_text()
    assert 'backend="aws"' in src
    assert 'execution_mode="cloud"' in src
    # registration now happens in _register_cloud_run, called by the
    # CloudRunController only after it has a real job id + S3 run
    assert "_register_cloud_run" in src
    assert "CloudRunController(" in src

    from cryostack_src.frontend.cryolauncher.cloud_run_controller import (
        CloudRunController,
    )
    calls = []

    class _Bridge:
        def submit(self, **kw):
            class _R:
                job_id = None            # no job id -> must NOT register
                metadata = {}
                working_directory = None
                messages = []
            return _R()

    ctl = CloudRunController(
        bridge_factory=_Bridge,
        register_run=lambda **kw: calls.append(kw),
        sync_results=lambda **kw: "/x",
        on_state=lambda s: None,
        on_log=lambda m: None,
        poll_interval=0.0,
    )
    import asyncio
    asyncio.run(ctl.run_once(staged_source="/x", model="issm",
                             run_target="runme.m", bucket="b"))
    assert calls == []                     # no job id -> no registration
    assert ctl.state == "failed"


def test_cloud_state_chip_covers_the_documented_states():
    src = _ICESHEETS.read_text()
    for state in ("not_configured", "checking", "ready", "staging", "submitting",
                  "queued", "running", "completed", "failed", "cancelled"):
        assert f'"{state}"' in src


def test_local_and_remote_paths_are_unchanged():
    src = _ICESHEETS.read_text()
    # Remote: the B3 identity gate + real submitters still present
    assert "enforce_remote_access(" in src
    assert "submit_remote_icesheets" in src
    assert "verify_remote_identity(" in src
    # Local: the local runner path
    assert "run_example_local" in src or "local" in src.lower()
    # cloud staging reuses the SAME working-copy helper as Remote
    assert "stage_example_for_run(" in src


def test_no_developer_or_personal_cloud_defaults():
    src = _ICESHEETS.read_text()
    for bad in ("us-east-1", "arobel3", "bankyanjo", "1711@matlablic"):
        assert bad not in src, bad
    assert "DEFAULT_CLOUD_REGION" in src  # region comes from the shared constant


@pytest.mark.parametrize("builder", ["build_icesheets_ui"])
def test_gateway_still_builds_with_the_cloud_wiring(builder, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "cloud-wire-user")
    monkeypatch.setenv("USER", "cloud-wire-service")
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()
    html = []

    def walk(w):
        if isinstance(w, W.HTML):
            html.append(w.value)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    blob = "\n".join(html)
    assert "Cloud: Not configured" in blob


# -- C7 live-acceptance: a failed AWS connection is not "Not configured" ---
def test_recovery_actions_and_new_chip_states_are_wired():
    src = _ICESHEETS.read_text()
    assert "connection_issue" in src and "Connection issue" in src
    assert "connection_required" in src and "Connection required" in src
    assert "aws_connect.retry" in src
    assert "aws_connect.change_account" in src
    assert "retry_button.on_click(aws_connect.retry)" in src
    assert "change_account_button.on_click(aws_connect.change_account)" in src
    # Change AWS account is staged: the replacement's own verify/cancel are
    # wired too, distinct from the active connection's verify/disconnect.
    assert "change_verify_button.on_click(aws_connect.change_verify)" in src
    assert "change_cancel_button.on_click(aws_connect.change_cancel)" in src


def test_a_stranded_aws_connection_shows_connection_issue_not_not_configured(monkeypatch, tmp_path):
    """The exact live-acceptance bug: a previously-attempted-but-failed AWS
    connection must render as "Cloud: Connection issue", never silently
    fall back to the first-time "Cloud: Not configured" label."""
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "cloud-recovery-user")
    monkeypatch.setenv("USER", "cloud-wire-service")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")

    from cryostack_src.cloud.connect import AWSConnectionStore
    from cryostack_src.workspace.identity import WorkspaceUser

    user = WorkspaceUser(user_id="cloud-recovery-user", source="env-override")
    store = AWSConnectionStore(user=user, workspace_root=tmp_path)
    conn = store.create(region="us-east-2").with_role(
        "arn:aws:iam::713938953301:role/CryoStackExecutionRole"
    ).mark_error("AWS denied the role assumption.")
    store.save(conn)

    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()
    html = []

    def walk(w):
        if isinstance(w, W.HTML):
            html.append(w.value)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    blob = "\n".join(html)
    assert "Cloud: Connection issue" in blob
    assert "Cloud: Not configured" not in blob
    # the Role ARN this user already saved must still be on disk, untouched
    assert store.load().role_arn == "arn:aws:iam::713938953301:role/CryoStackExecutionRole"


# -- Icepack Cloud Execution checkpoint -----------------------------------
def test_canonical_cloud_config_derives_the_selected_model():
    """The functions that build the Review card / drift digest / launch gate
    no longer hardcode model="issm" -- they read model_dd.value. (The
    ISSM-only scientific_overrides conditional is intentional and untouched.)"""
    src = _ICESHEETS.read_text()
    assert 'model=(model_dd.value or "issm").strip().lower()' in src
    # the old hardcoded-issm-only comment on _resolve_cloud_execution is gone
    assert 'model="issm",           # cloud execution is ISSM-only for now' not in src


def test_cloud_run_history_and_execution_follow_the_selected_model():
    src = _ICESHEETS.read_text()
    assert '(run.model or "").lower() != _model' in src
    assert "region_hint=aws_region.value.strip() or DEFAULT_CLOUD_REGION" in src
    # the ISSM-only note is gone from _resolve_cloud_execution
    assert "cloud execution is ISSM-only for now" not in src


def test_gateway_builds_with_icepack_selectable_and_cloud_supported():
    """Icepack Cloud Execution checkpoint: the model dropdown includes
    Icepack, and the capabilities registry (which the gateway/agent both
    read) now agrees Icepack is cloud-capable."""
    from cryostack_src.models.capabilities import get_model_capabilities

    cap = get_model_capabilities("icepack")
    assert cap.cloud_supported is True
    assert "cloud" in cap.execution_modes
    assert cap.requires_matlab is False

    issm_cap = get_model_capabilities("issm")
    assert issm_cap.cloud_supported is True
    assert issm_cap.requires_matlab is True             # ISSM behaviour unchanged


# ── Launch cloud run must never reach Remote/HPC validation ───────────────
# Live-acceptance bug at commit 5c7f0d10: Launch cloud run (Icepack, Review
# passed) produced "[remote][ERROR] Host and User are required." -- the
# button's callback fell through into on_run()'s Remote/HPC dispatch instead
# of the cloud/AWS controller. Root cause: (1) on_run()'s Host/User check was
# unconditional (fired for every execution mode, not just "remote"), and
# (2) nothing set mode_dd back to "cloud" for a user who never touched the
# main Execution Mode dropdown and drove the run entirely from the Cloud
# Environment panel, so on_run() read the stale default ("remote").
#
# Fix: Launch cloud run's callback (_launch_cloud_run) is wired directly as
# cloud_review_runtime's launch_handler -- it never calls on_run() at all,
# so it structurally cannot reach the Remote/HPC checks, regardless of
# mode_dd's value. on_run()'s own Host/User check is also now correctly
# gated on mode == "remote" (defence in depth for the generic Run button).


def _freevar(fn, name):
    """Extract one captured (closure) variable from a nested function by
    name -- the only way to reach icesheets_gateway.py's internals, which
    are deliberately not module-level (every existing test in this file
    verifies this legacy gateway's wiring the same way: build the real
    gateway, then inspect it)."""
    idx = fn.__code__.co_freevars.index(name)
    return fn.__closure__[idx].cell_contents


def _build_gateway_and_launch_handler(monkeypatch, tmp_path, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", "cloud-wire-service")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()

    launch_button = None

    def walk(w):
        nonlocal launch_button
        if isinstance(w, W.Button) and getattr(w, "description", "") == "Launch cloud run":
            launch_button = w
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    assert launch_button is not None, "Launch cloud run button not found in the built page"
    assert launch_button._click_handlers.callbacks, "Launch cloud run has no click handler"

    review_launch = launch_button._click_handlers.callbacks[0]   # cloud_review_runtime.launch
    launch_handler = _freevar(review_launch, "launch_handler")   # _launch_cloud_run
    return launch_handler


@pytest.mark.parametrize("model", ["icepack", "issm"])
def test_launch_cloud_run_never_reaches_remote_host_user_validation(
    monkeypatch, tmp_path, capsys, model
):
    """The exact live path: build the real gateway, select the model, invoke
    the REAL function object wired as Launch cloud run's callback -- proving
    it (a) is not on_run, (b) cannot call on_run (not even in its closure),
    and (c) running it never produces the Remote/HPC Host/User message,
    for BOTH Icepack and ISSM."""
    launch_handler = _build_gateway_and_launch_handler(
        monkeypatch, tmp_path, user=f"cloud-launch-{model}")

    # (a)/(b): structurally cannot reach on_run -- it is not even a captured
    # free variable of the Launch cloud run callback.
    assert "on_run" not in launch_handler.__code__.co_freevars

    prepare = _freevar(launch_handler, "_prepare_effective_example")
    example_dir_w = _freevar(prepare, "example_dir")
    model_dd_w = _freevar(prepare, "model_dd")

    example = tmp_path / "SmallestExample"
    example.mkdir()
    (example / "run.py").write_text("print('hello')\n")
    (example / "runme.m").write_text("% issm entry\n")

    model_dd_w.value = model
    example_dir_w.value = str(example)

    # deliberately leave cluster_host/cluster_user at their untouched
    # defaults -- exactly the live report's state (the user never touched
    # the Remote HPC connection fields; only the Cloud Environment panel).
    capsys.readouterr()   # drop anything printed during gateway construction
    # (c): the callback runs to whatever conclusion it reaches offline (no
    # AWS configured -> a clean [cloud] config/preflight message), but it
    # NEVER emits the Remote/HPC Host/User error.
    launch_handler(None)

    printed = capsys.readouterr().out
    assert "[remote][ERROR] Host and User are required." not in printed
    assert "cluster" not in printed.lower()


def test_launch_cloud_run_callback_is_not_on_run_itself():
    """Static, non-behavioural confirmation of the wiring: the source no
    longer connects Launch cloud run to on_run through the old
    pending_review + on_run(None) lambda."""
    src = _ICESHEETS.read_text()
    assert "launch_handler=_launch_cloud_run" in src
    assert 'launch_handler=lambda review: (\n                _cloud.__setitem__' not in src
    # _launch_cloud_run's own CODE (docstring excluded -- it explains the
    # invariant in prose, which legitimately names the very things the code
    # must not touch) never references Remote/HPC state.
    start = src.index("def _launch_cloud_run(")
    end = src.index("\n        def on_run(", start)
    definition = src[start:end]
    docstring_end = definition.index('"""', definition.index('"""') + 3) + 3
    code = definition[docstring_end:]
    for forbidden in ("cluster_host", "cluster_user", "enforce_remote_access",
                      "on_run(", "mode_dd"):
        assert forbidden not in code, forbidden


# ── Icepack notebook staging: Advanced Editor shows the runnable script ────
def _find_widget_by_observer(page, handler_name: str):
    found = {}

    def walk(w):
        if handler_name not in found:
            notifiers = getattr(w, "_trait_notifiers", None)
            if notifiers and "value" in notifiers:
                for handlers in notifiers["value"].values():
                    for h in handlers:
                        if getattr(h, "__name__", "") == handler_name:
                            found[handler_name] = (w, h)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    return found.get(handler_name)


def test_selecting_an_icepack_notebook_example_materializes_run_py_for_the_editor(
    monkeypatch, tmp_path
):
    """Root cause + item 5: selecting a canonical Icepack tutorial (a bare
    .ipynb file -- the exact discovery shape that produced "Example
    directory not found") must leave example_dir pointing at a real
    directory containing the deterministic run.py, so the Advanced Editor
    shows/edits the runnable Python representation, not raw notebook JSON --
    and every downstream consumer (staging) sees an ordinary directory.
    Skips when this machine has no local Icepack checkout to discover."""
    from icesee_jupyter_book.core.icesheet_examples import resolve_icepack_root

    root = resolve_icepack_root()
    if root is None:
        pytest.skip("no local Icepack checkout on this machine")
    notebook = root / "notebooks" / "tutorials" / "00-meshes-functions.ipynb"
    if not notebook.is_file():
        pytest.skip("00-meshes-functions.ipynb not present in this Icepack checkout")

    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "editor-notebook-user")
    monkeypatch.setenv("USER", "cloud-wire-service")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()

    picker, handler = _find_widget_by_observer(page, "apply_selected_example")

    def freevar(fn, name):
        idx = fn.__code__.co_freevars.index(name)
        return fn.__closure__[idx].cell_contents

    model_dd = freevar(handler, "model_dd")
    example_dir = freevar(handler, "example_dir")
    run_target = freevar(handler, "run_target")
    editor_panel = freevar(handler, "editor_panel")

    model_dd.value = "icepack"          # repopulates the picker via refresh_example_picker
    target = str(notebook.resolve())
    assert target in [v for _l, v in picker.options]

    picker.value = target               # fires apply_selected_example (real handler)

    staged = Path(example_dir.value)
    assert staged.is_dir(), "example_dir must be a directory, never the bare .ipynb"
    assert (staged / "run.py").is_file()
    assert (staged / notebook.name).is_file()          # the source notebook is kept too
    assert "import" in (staged / "run.py").read_text()

    # item 10: the actual Advanced Editor file-selection callback/state --
    # not just the filesystem it reads from.
    ctl = editor_panel.controller
    assert run_target.value == "run.py"
    assert Path(ctl.file_picker.value).name == "run.py"          # active editor file
    assert ctl.editor.value == (staged / "run.py").read_text()  # generated Python...
    assert not ctl.editor.value.lstrip().startswith("{")         # ...never notebook JSON
    assert ctl.editor.disabled is False                          # run.py is editable


def test_deliberately_selecting_the_notebook_keeps_it_readonly_raw(monkeypatch, tmp_path):
    """Item 6: the .ipynb stays reachable and, once explicitly picked, stays
    read-only raw JSON -- we are not rendering notebooks in this checkpoint."""
    from icesee_jupyter_book.core.icesheet_examples import resolve_icepack_root

    root = resolve_icepack_root()
    if root is None:
        pytest.skip("no local Icepack checkout on this machine")
    notebook = root / "notebooks" / "tutorials" / "00-meshes-functions.ipynb"
    if not notebook.is_file():
        pytest.skip("00-meshes-functions.ipynb not present in this Icepack checkout")

    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "editor-notebook-user2")
    monkeypatch.setenv("USER", "cloud-wire-service")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()

    picker, handler = _find_widget_by_observer(page, "apply_selected_example")

    def freevar(fn, name):
        idx = fn.__code__.co_freevars.index(name)
        return fn.__closure__[idx].cell_contents

    model_dd = freevar(handler, "model_dd")
    editor_panel = freevar(handler, "editor_panel")
    model_dd.value = "icepack"
    picker.value = str(notebook.resolve())
    ctl = editor_panel.controller

    # the default is run.py (proven above) -- now deliberately switch to .ipynb
    nb_option = next(v for _l, v in ctl.file_picker.options if v.endswith(".ipynb"))
    ctl.file_picker.value = nb_option
    assert ctl.editor.disabled is True
    assert ctl.editor.value.lstrip().startswith("{")   # raw notebook JSON, unrendered


def test_refresh_never_reverts_an_open_run_py_back_to_the_notebook(monkeypatch, tmp_path):
    """Item 7: Refresh must not switch the active file away from run.py."""
    from icesee_jupyter_book.core.icesheet_examples import resolve_icepack_root

    root = resolve_icepack_root()
    if root is None:
        pytest.skip("no local Icepack checkout on this machine")
    notebook = root / "notebooks" / "tutorials" / "00-meshes-functions.ipynb"
    if not notebook.is_file():
        pytest.skip("00-meshes-functions.ipynb not present in this Icepack checkout")

    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "editor-notebook-user3")
    monkeypatch.setenv("USER", "cloud-wire-service")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()

    picker, handler = _find_widget_by_observer(page, "apply_selected_example")

    def freevar(fn, name):
        idx = fn.__code__.co_freevars.index(name)
        return fn.__closure__[idx].cell_contents

    model_dd = freevar(handler, "model_dd")
    editor_panel = freevar(handler, "editor_panel")
    model_dd.value = "icepack"
    picker.value = str(notebook.resolve())
    ctl = editor_panel.controller
    assert Path(ctl.file_picker.value).name == "run.py"

    ctl.refresh()                                       # the editor's own Refresh button
    assert Path(ctl.file_picker.value).name == "run.py", (
        "Refresh must not silently switch the active file back to the notebook"
    )


# ── C7.5 live-acceptance: CLOUD RUN card must be the single run-control ───
# surface for cloud mode. Live finding on job ec56a332-7832-4933-936d-
# e98f236d0e37: while a cloud run was active, the page rendered BOTH the
# CLOUD RUN card (View log / View results / Terminate, wired through the
# account-aware CloudRunController) and the older generic Execution panel
# below it (state + "Submit job" + its own "Terminate") -- a second,
# non-account-bound path to the same job. For execution_mode == "cloud" the
# generic panel's Submit job / Terminate must be hidden; Remote is
# unaffected (this gateway's Execution Mode dropdown only ever offers
# "Remote" / "Cloud" -- there is no separate "Local" mode to toggle here).
def _build_gateway_page(monkeypatch, tmp_path, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", "cloud-wire-service")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    return build_icesheets_ui()


def test_cloud_mode_hides_the_duplicate_generic_submit_and_terminate_controls(
    monkeypatch, tmp_path
):
    """Cloud mode: the generic Execution panel's "Submit job" (run_btn) and
    its own Terminate (cloud_terminate_btn) are both hidden -- the CLOUD RUN
    card (a structurally distinct widget, built in cloud_environment.py) is
    the only reachable run-control surface. Remote mode -- the only other
    execution_mode this gateway offers -- renders exactly as it always has:
    run_btn visible, the remote Terminate button visible, cloud_terminate_btn
    still hidden (it always was, outside cloud mode)."""
    page = _build_gateway_page(monkeypatch, tmp_path, user="cloud-ui-hide-user")

    _, update_visibility = _find_widget_by_observer(page, "update_visibility")
    mode_dd = _freevar(update_visibility, "mode_dd")
    ui_mode_dd = _freevar(update_visibility, "ui_mode_dd")
    run_btn = _freevar(update_visibility, "run_btn")
    cloud_terminate_btn = _freevar(update_visibility, "cloud_terminate_btn")
    terminate_btn = _freevar(update_visibility, "terminate_btn")

    assert ui_mode_dd.value != "agent"          # the manual Basic/Advanced surface

    # -- Cloud mode: the CLOUD RUN card alone controls a run --------------
    mode_dd.value = "cloud"
    assert run_btn.layout.display == "none", "generic Submit job must be hidden in cloud mode"
    assert cloud_terminate_btn.layout.display == "none", (
        "generic Terminate must be hidden in cloud mode -- CLOUD RUN's own "
        "Terminate (a separate widget) is the only run-control surface"
    )

    # -- Remote mode (this gateway's only other execution_mode): unchanged -
    mode_dd.value = "remote"
    assert run_btn.layout.display == "", "Remote must keep Submit job visible, unchanged"
    assert terminate_btn.layout.display == "", "Remote's own Terminate stays visible, unchanged"
    assert cloud_terminate_btn.layout.display == "none", (
        "cloud_terminate_btn was already hidden outside cloud mode before this fix"
    )


def test_cloud_run_card_terminate_is_a_structurally_distinct_widget_from_the_generic_one(
    monkeypatch, tmp_path
):
    """The CLOUD RUN card's Terminate button (wired to CloudRunController via
    on_cloud_terminate_confirm) is a DIFFERENT Button object than the generic
    Execution panel's cloud_terminate_btn -- hiding the latter cannot also
    remove the former, and the former's own visibility is driven independently
    (cloud_active_run_runtime / set_active_run_view), not by update_visibility."""
    page = _build_gateway_page(monkeypatch, tmp_path, user="cloud-ui-distinct-user")

    _, update_visibility = _find_widget_by_observer(page, "update_visibility")
    cloud_terminate_btn = _freevar(update_visibility, "cloud_terminate_btn")

    terminate_buttons = []

    def walk(w):
        if isinstance(w, W.Button) and getattr(w, "description", "") == "Terminate":
            terminate_buttons.append(w)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    assert len(terminate_buttons) == 2, "expected exactly the generic + CLOUD RUN terminate buttons"
    assert cloud_terminate_btn in terminate_buttons
    active_run_terminate = next(b for b in terminate_buttons if b is not cloud_terminate_btn)
    assert active_run_terminate is not cloud_terminate_btn


# ── C7.5 live-acceptance: "Container Overrides length must be at most 8192" ─
# Live finding: SubmitJob/staging succeeded for account 774888247882, but the
# job then failed with this exact AWS message -- traced to the Icepack output
# collector being embedded VERBATIM into the Batch job definition's command
# (cryostack_src/cloud/runtime.py), which AWS forwards through an ECS RunTask
# override on every launch, capped at 8192 characters. The fix stages the
# collector as an ordinary file alongside run.py
# (cryostack_src.cloud.runtime.icepack_postprocess_extra_files) instead --
# this test proves the ACTUAL wired gateway code path
# (_submit_cloud_run's own "cloud always uploads a user-owned working copy"
# staging call) passes that exact extra_files entry to
# WorkspaceManager.stage_example_for_run for an Icepack cloud run, without
# contacting AWS.
def test_icepack_cloud_submit_stages_the_postprocess_helper_alongside_run_py(
    monkeypatch, tmp_path
):
    from cryostack_src.cloud.runtime import (
        ICEPACK_POSTPROCESS_FILENAME,
        icepack_postprocess_extra_files,
    )

    launch_handler = _build_gateway_and_launch_handler(
        monkeypatch, tmp_path, user="icepack-8192-user")
    submit_fn = _freevar(launch_handler, "_submit_cloud_run")

    model_dd = _freevar(submit_fn, "model_dd")
    example_dir = _freevar(submit_fn, "example_dir")
    run_target = _freevar(submit_fn, "run_target")
    aws_region = _freevar(submit_fn, "aws_region")
    cloud_bucket = _freevar(submit_fn, "cloud_bucket")
    aws_profile = _freevar(submit_fn, "aws_profile")
    batch_job_queue = _freevar(submit_fn, "batch_job_queue")
    batch_job_def = _freevar(submit_fn, "batch_job_def")
    workspace_manager = _freevar(submit_fn, "workspace_manager")

    example = tmp_path / "IcepackExample"
    example.mkdir()
    (example / "run.py").write_text("print('hello icepack')\n")

    model_dd.value = "icepack"
    example_dir.value = str(example)
    run_target.value = "run.py"
    # enough to pass validate_cloud_config/cloud_run_preflight's pure string
    # checks -- no AWS is ever contacted by those, or by this test.
    aws_region.value = "us-east-2"
    cloud_bucket.value = "cryostack-runs-774888247882"
    aws_profile.value = ""
    batch_job_queue.value = "cryostack-queue"
    batch_job_def.value = "cryostack-icepack"

    captured = {}

    def fake_stage_example_for_run(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop before any AWS contact -- staging kwargs already captured")

    monkeypatch.setattr(workspace_manager, "stage_example_for_run", fake_stage_example_for_run)

    # _submit_cloud_run(staged_dir, md_provenance, review=None) -- staged_dir
    # equal to example_dir.value is exactly what triggers its own "cloud
    # always uploads a user-owned working copy" staging fallback (the path
    # a plain Advanced-mode Icepack run with no Basic-mode overrides takes --
    # the live failing job's own shape).
    submit_fn(example_dir.value, {}, review=None)

    assert "extra_files" in captured, "the staging call never ran (still blocked earlier)"
    extra = captured["extra_files"]
    assert extra is not None and ICEPACK_POSTPROCESS_FILENAME in extra
    assert extra[ICEPACK_POSTPROCESS_FILENAME] == icepack_postprocess_extra_files()[
        ICEPACK_POSTPROCESS_FILENAME]


def test_issm_cloud_submit_never_gets_the_icepack_extra_file(monkeypatch, tmp_path):
    """ISSM behaviour is untouched: its own staging call never carries the
    Icepack-only extra_files entry."""
    from cryostack_src.cloud.runtime import ICEPACK_POSTPROCESS_FILENAME

    launch_handler = _build_gateway_and_launch_handler(
        monkeypatch, tmp_path, user="issm-8192-user")
    submit_fn = _freevar(launch_handler, "_submit_cloud_run")

    model_dd = _freevar(submit_fn, "model_dd")
    example_dir = _freevar(submit_fn, "example_dir")
    run_target = _freevar(submit_fn, "run_target")
    aws_region = _freevar(submit_fn, "aws_region")
    cloud_bucket = _freevar(submit_fn, "cloud_bucket")
    aws_profile = _freevar(submit_fn, "aws_profile")
    batch_job_queue = _freevar(submit_fn, "batch_job_queue")
    batch_job_def = _freevar(submit_fn, "batch_job_def")
    workspace_manager = _freevar(submit_fn, "workspace_manager")

    example = tmp_path / "SquareIceShelf"
    example.mkdir()
    (example / "runme.m").write_text("md=solve(md,'Stressbalance');\n")

    model_dd.value = "issm"
    example_dir.value = str(example)
    run_target.value = "runme.m"
    aws_region.value = "us-east-2"
    cloud_bucket.value = "cryostack-runs-774888247882"
    aws_profile.value = ""
    batch_job_queue.value = "cryostack-queue"
    batch_job_def.value = "cryostack-issm"

    # ISSM's own preflight gate (a cloud MATLAB license -- an AWS Secrets
    # Manager ARN on the connection) is unrelated to this checkpoint; stub
    # the gateway's preflight so the test reaches the staging call at all.
    import icesee_jupyter_book.ui.icesheets_gateway as _gw
    monkeypatch.setattr(_gw, "cloud_run_preflight", lambda **kw: [])

    captured = {}

    def fake_stage_example_for_run(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop before any AWS contact -- staging kwargs already captured")

    monkeypatch.setattr(workspace_manager, "stage_example_for_run", fake_stage_example_for_run)
    submit_fn(example_dir.value, {}, review=None)

    assert "extra_files" in captured, "the staging call never ran (still blocked earlier)"
    assert not captured["extra_files"]         # None (or empty) for ISSM
    if captured["extra_files"]:
        assert ICEPACK_POSTPROCESS_FILENAME not in captured["extra_files"]


# ── checkpoint: container provenance + execution-summary semantics ───────
def _summary_internals(monkeypatch, tmp_path, *, user):
    page = _build_gateway_page(monkeypatch, tmp_path, user=user)
    _, update_visibility = _find_widget_by_observer(page, "update_visibility")
    update_summary = _freevar(update_visibility, "update_summary")
    return {
        "page": page,
        "update_visibility": update_visibility,
        "update_summary": update_summary,
        "summary_html": _freevar(update_summary, "summary_html"),
        "mode_dd": _freevar(update_summary, "mode_dd"),
        "model_dd": _freevar(update_summary, "model_dd"),
        "backend_dd": _freevar(update_summary, "backend_dd"),
        "command_preview": _freevar(update_summary, "command_preview"),
        "run_target": _freevar(update_summary, "run_target"),
        "STATUS": _freevar(update_summary, "STATUS"),
        "md_config_panel": _freevar(update_visibility, "md_config_panel"),
        "icepack_config_panel": _freevar(update_visibility, "icepack_config_panel"),
    }


def test_execution_summary_has_an_explicit_cloud_branch(monkeypatch, tmp_path):
    """A cloud run must not read backend_dd (still 'spack' by default) -- it
    shows the AWS Batch compute substrate, the container model environment,
    and the exact tested image tag + digest."""
    from cryostack_src.models.stack import default_tested_image_for_model

    g = _summary_internals(monkeypatch, tmp_path, user="cloud-summary-user")
    g["model_dd"].value = "icepack"
    g["backend_dd"].value = "spack"          # deliberately the stale default
    g["mode_dd"].value = "cloud"
    g["update_summary"]()

    html = g["summary_html"].value
    assert "Execution mode:</span> Cloud" in html
    assert "Cloud backend:</span> AWS Batch (Fargate)" in html
    assert "Model environment:</span> ICESEE-Container (Spack-built stack)" in html
    assert "Model:</span> ICEPACK" in html
    assert "ICESEE-Spack" not in html                 # the old wrong label is gone
    img = default_tested_image_for_model("icepack")
    assert img.reference in html
    assert img.digest[:22] in html
    # command preview no longer shows a spack / apptainer command
    cmd = g["command_preview"].value
    assert "aws batch submit-job" in cmd
    assert "apptainer" not in cmd and "spack" not in cmd.lower()


def test_execution_summary_remote_spack_and_container_unchanged(monkeypatch, tmp_path):
    g = _summary_internals(monkeypatch, tmp_path, user="remote-summary-user")
    g["model_dd"].value = "issm"
    g["mode_dd"].value = "remote"

    g["backend_dd"].value = "spack"
    g["update_summary"]()
    html_spack = g["summary_html"].value
    assert "Backend:</span> ICESEE-Spack" in html_spack
    assert "Cloud backend:" not in html_spack

    g["backend_dd"].value = "container"
    g["update_summary"]()
    html_container = g["summary_html"].value
    assert "Backend:</span> ICESEE-Container" in html_container
    assert "Cloud backend:" not in html_container


def test_cloud_submit_freezes_the_container_image_into_run_provenance(monkeypatch, tmp_path):
    """_register_cloud_run must persist the exact tested image tag + digest
    AND a container/software provenance block (the SAME manifest schema the
    Remote container path uses) so a historical run never drifts when the
    default image changes."""
    from cryostack_src.models.stack import default_tested_image_for_model

    launch_handler = _build_gateway_and_launch_handler(
        monkeypatch, tmp_path, user="cloud-prov-user")
    submit_fn = _freevar(launch_handler, "_submit_cloud_run")
    _cloud = _freevar(submit_fn, "_cloud")
    reg = _cloud["controller"]._register_run          # == _register_cloud_run
    workspace_bridge = _freevar(reg, "workspace_bridge")

    started = {}

    def fake_start_run(**kw):
        started.update(kw)

    monkeypatch.setattr(workspace_bridge, "start_run", fake_start_run)

    img = default_tested_image_for_model("icepack")

    class _Handle:
        model = "icepack"
        job_id = "job-xyz"
        run_id = "run-xyz"
        s3_run = "s3://cryostack-runs-774888247882/runs/u/run-xyz"
        region = "us-east-2"
        account_id = "774888247882"
        example = "00-meshes-functions"
        run_target = "run.py"
        source = "00-meshes-functions.ipynb"
        vcpu = 2
        memory_gib = 8
        expected_runtime_minutes = 5
        cost_public = {}
        metadata = {}
        image_key = img.key
        image_label = img.label
        image_reference = img.reference
        image_digest = img.digest

    class _Result:
        metadata = {"job_queue": "q", "job_definition": "cryostack-icepack"}

    reg(handle=_Handle(), result=_Result())

    md = started["metadata"]
    assert md["image_reference"] == img.reference
    assert md["image_digest"] == img.digest
    assert md["image_key"] == img.key
    # experiment identity persisted distinctly: example / source / run target
    assert md["example"] == "00-meshes-functions"
    assert md["source"] == "00-meshes-functions.ipynb"    # the .ipynb, not run.py
    assert md["run_target"] == "run.py"                   # what AWS Batch executed
    # reused container/software provenance schema (not a cloud-only format)
    container = started["container"]
    assert container["source"] == "docker"
    assert container["digest"] == img.digest
    assert img.reference in container["reference"]
    assert container["build_provenance"]["tested_image"] == img.key
    assert started["software"]                      # per-component provenance present
    assert started["backend"] == "aws"
    assert started["execution_mode"] == "cloud"


# ── UI-semantic cleanup: Basic-mode config title, cloud Run Plan source ──
def test_basic_config_accordion_follows_the_selected_model(monkeypatch, tmp_path):
    """Switching model must retitle the Basic-mode configuration accordion:
    Icepack selected -> the Icepack panel is shown, the ISSM panel hidden
    (and vice versa). Regression: update_visibility was not re-run on a
    model switch, so 'ISSM configuration (Basic)' stayed visible for
    Icepack."""
    g = _summary_internals(monkeypatch, tmp_path, user="basic-title-user")
    md, ip = g["md_config_panel"], g["icepack_config_panel"]

    g["model_dd"].value = "icepack"
    assert ip.layout.display == "" and md.layout.display == "none"
    assert ip.get_title(0) == "⚙️ Icepack configuration (Basic)"

    g["model_dd"].value = "issm"                      # ISSM behaviour preserved
    assert md.layout.display == "" and ip.layout.display == "none"
    assert md.get_title(0) == "⚙️ ISSM configuration (Basic)"


def test_cloud_run_plan_distinguishes_notebook_source_from_run_py(monkeypatch, tmp_path):
    g = _summary_internals(monkeypatch, tmp_path, user="runplan-nb-user")
    g["model_dd"].value = "icepack"
    g["mode_dd"].value = "cloud"
    g["STATUS"]["selected_example_path"] = (
        "/home/u/icepack/notebooks/tutorials/00-meshes-functions.ipynb")
    g["run_target"].value = "run.py"
    g["update_summary"]()

    html = g["summary_html"].value
    assert "Example:</span> 00-meshes-functions" in html
    assert "Source:</span> <code>00-meshes-functions.ipynb</code>" in html
    assert "converted to <code>run.py</code> before staging" in html
    assert "Run target:</span> <code>run.py</code>" in html
    # never implies AWS runs the .ipynb
    assert ">00-meshes-functions.ipynb</code> <span class='icesee-subtle'>(executed on AWS Batch)" not in html
    assert "Selected example:" not in html            # the vague old line is gone


def test_cloud_run_plan_stays_truthful_for_an_issm_example(monkeypatch, tmp_path):
    g = _summary_internals(monkeypatch, tmp_path, user="runplan-issm-user")
    g["model_dd"].value = "issm"
    g["mode_dd"].value = "cloud"
    g["STATUS"]["selected_example_path"] = "/home/u/ISSM/examples/SquareIceShelf"
    g["run_target"].value = "runme.m"
    g["update_summary"]()

    html = g["summary_html"].value
    assert "Example:</span> SquareIceShelf" in html
    assert "Run target:</span> <code>runme.m</code>" in html
    # a directory example has no separate "Source:" file -- not fabricated
    assert "Source:</span>" not in html
    assert "converted to" not in html                 # no notebook language for ISSM


def test_advanced_cloud_settings_helper_states_the_blank_equals_prepared_contract(
    monkeypatch, tmp_path
):
    page = _build_gateway_page(monkeypatch, tmp_path, user="adv-helper-user")
    htmls = []

    def walk(w):
        if isinstance(w, W.HTML):
            htmls.append(w.value)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    caption = next((h for h in htmls if "Leave these fields blank" in h), "")
    assert caption, "advanced-cloud-settings helper text not found"
    assert "CryoStack-prepared resources for the connected AWS account" in caption
    assert "override that specific resource" in caption
    assert "Developer / override settings." not in "\n".join(htmls)   # old text gone
