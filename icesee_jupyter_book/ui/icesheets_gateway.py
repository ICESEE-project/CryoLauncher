from __future__ import annotations

import os
import io
import html
import json
import time as _time
import yaml
import subprocess
from pathlib import Path

from tornado.ioloop import PeriodicCallback

from IPython.display import HTML
import base64

import ipywidgets as W
from IPython.display import display

from icesee_jupyter_book.core.icesheet_examples import (
    merged_examples_for_model,
    example_summary_text,
)
from icesee_jupyter_book.core.remote_runner import (
    ssh_run,
    slurm_optional_lines,
    resolve_remote_abs_path,
    remote_stage_and_submit,
    sanitize_multiline,
    bootstrap_passwordless_ssh,
    connector_ssh,
    connector_fetch_archive,
    connector_stage_archive,
    connector_slurm_submit,
    connector_get_public_key,
)
from cryostack_src.cloud.bridge import CloudBridge
from cryostack_src.cloud import (
    DEFAULT_CLOUD_REGION,
    cloud_run_preflight,
    resolve_cloud_config,
    validate_cloud_config,
)

from icesee_jupyter_book.core.local_connector import build_connector_panel
from icesee_jupyter_book.ui.shared_ssh_widgets import build_ssh_key_manager
from icesee_jupyter_book.core.connector_relay_client import (
    create_session,
    check_status as relay_check_status,
    send_command,
)

from icesee_jupyter_book.ui.application_menus import (
    build_icesheets_app_menu,
    load_cryostack_account_assets,
)

from icesee_jupyter_book.ui.shared_app_styles import (
    shared_application_styles,
)
from icesee_jupyter_book.ui.shared_remote_connection_panel import (
    build_remote_connection_panel,
    classify_bootstrap_result,
)
from icesee_jupyter_book.ui.shared_slurm_resources_panel import (
    build_slurm_resources_panel,
)
from icesee_jupyter_book.ui.shared_validation import (
    validate_slurm_resources,
)
from icesee_jupyter_book.ui.shared_observer_guard import UIRefreshCoordinator
from icesee_jupyter_book.ui.shared_agent_panel import build_agent_accordion
from cryostack_src import perf

from icesee_jupyter_book.ui.experiment_bridge import (
    ExperimentBridge,
    load_experiment_bridge,
)

import getpass

from icesee_jupyter_book.ui.workspace_bridge import (
    WorkspaceBridge as WorkspacePersistenceBridge,
    load_workspace_bridge,
)
from icesee_jupyter_book.ui.workspace_persistence import make_state_io

from cryostack_src.workspace import (
    WorkspaceBridge,
    WorkspaceManager,
    build_workspace_logs,
    resolve_workspace_user,
)
from cryostack_src.workspace.resource_state import (
    ResourceStateController,
    strip_secrets,
)

from icesee_jupyter_book.core.experiment_status import (
    experiment_update_from_job_status,
)


from cryostack_src.frontend.shared import (
    CRYOSTACK_FRONTEND_CSS,
    status_badge as status_badge_html,
)

from cryostack_src.frontend.cryolauncher.cloud_environment import (
    build_cloud_environment_card,
    set_cloud_status,
)
from cryostack_src.frontend.cryolauncher.cloud_runtime import (
    build_cloud_runtime_callbacks,
)
from cryostack_src.frontend.cryolauncher.cloud_connect_runtime import (
    build_aws_connect_callbacks,
)
from cryostack_src.frontend.cryolauncher.cloud_run_controller import (
    CloudRunController,
    cloud_run_plan_summary,
    resolve_job_definition,
    user_run_prefix,
)
from cryostack_src.cloud.drivers.aws.batch_config import (
    JOB_DEFINITION_NAMES as _CLOUD_JOB_DEFS,
)
from cryostack_src.frontend.cryolauncher.remote_runtime import (
    build_remote_runtime_callbacks,
)
from cryostack_src.remote import RemoteBridge, expand_remote_home, normalize_remote_path
from cryostack_src.remote.access_state import (
    enforce_remote_access,
    verify_remote_identity,
    identity_result_from_output,
    can_reuse_connectivity_identity,
    classify_ssh_failure,
    SSH_KEY_NOT_AUTHORIZED,
)
from cryostack_src.remote.spack_env import SetupSlurmOpts
from cryostack_src.frontend.cryolauncher.spack_runtime import build_spack_runtime_callbacks
from cryostack_src.models import get_model_adapter
from cryostack_src.models.issm.md_config import (
    build_md_override_script,
    inject_override_step,
)
from cryostack_src.models.stack import (
    ComponentResolutionError,
    ContainerIdentityError,
    StackCompatError,
    StackRuntimeError,
    resolve_stack,
    stack_log_line,
)
from cryostack_src.models.submission import (
    submit_remote_icesheets,
    submit_remote_icesheets_via_connector,
)
from cryostack_src.resources.profiles import get_compute_profile, initial_remote_fields
from cryostack_src.frontend.cryolauncher.software_stack import build_software_stack_panel
from cryostack_src.frontend.cryolauncher.container_image import build_container_image_panel
from cryostack_src.frontend.cryolauncher.issm_md_panel import build_issm_md_panel
from cryostack_src.frontend.cryolauncher.icepack_basic_panel import build_icepack_basic_panel
from cryostack_src.models.icepack.parameters import (
    IcepackOverrideError, IcepackParameterError, entrypoint_transform_for,
)
from cryostack_src.models.icepack.notebook import NotebookConversionError

from cryostack_src.frontend.cryolauncher.panels import (
    build_logs_panel,
    build_results_panel,
    build_run_settings_panel,
    build_status_panel,
    build_runtime_panel,
    build_run_plan_panel,

)

from cryostack_src.frontend.cryolauncher.workspace import (
    build_dataset_panel,
    build_editor_panel,
    build_run_details,
    build_visualization_panel,
    build_workspace_explorer,
    build_workspace_toolbar,
    build_workspace_history_panel,
)

from cryostack_src.frontend.cryolauncher.run_settings_state import (
    build_run_settings_state,
)

from cryostack_src.frontend.cryolauncher.runtime_state import (
    build_runtime_state,
    status_html,
)

# ============================================================
# Params widgets factory
# ============================================================
def widget_for(key: str, val):
    if isinstance(val, str):
        if key.lower() == "filter_type":
            opts = ["EnKF", "DEnKF", "EnTKF", "EnRSKF"]
            return W.Dropdown(options=opts, value=val if val in opts else opts[0], layout=W.Layout(width="100%"))
        if key.lower() in {"parallel_flag", "parallel"}:
            opts = ["serial", "MPI", "MPI_model"]
            return W.Dropdown(options=opts, value=val if val in opts else opts[0], layout=W.Layout(width="100%"))
        return W.Text(value=val, layout=W.Layout(width="100%"))

    if isinstance(val, bool):
        return W.Checkbox(value=val)

    if isinstance(val, int) and not isinstance(val, bool):
        return W.IntText(value=val, layout=W.Layout(width="100%"))
    if isinstance(val, float):
        return W.FloatText(value=val, layout=W.Layout(width="100%"))

    if isinstance(val, (list, dict)):
        return W.Textarea(
            value=yaml.safe_dump(val, sort_keys=False).strip(),
            layout=W.Layout(width="100%", height="110px"),
        )

    return W.Text(value=str(val), layout=W.Layout(width="100%"))


def read_widget(w):
    if isinstance(w, W.Textarea):
        try:
            return yaml.safe_load(w.value)
        except Exception:
            return w.value
    if hasattr(w, "value"):
        return w.value
    return None

def build_sidebar():
    sidebar_html = """
    <style>
    .icesee-shell {
      width: 100%;
      display: flex;
      min-height: 100vh;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    }

    .icesee-sidebar {
      width: 260px;
      min-width: 260px;
      background: #f8f9fb;
      border-right: 1px solid rgba(0,0,0,.08);
      padding: 18px 14px;
      box-sizing: border-box;
    }

    .icesee-sidebar h2 {
      font-size: 18px;
      margin: 0 0 16px 0;
      font-weight: 800;
    }

    .icesee-nav-group {
      margin: 18px 0 8px 0;
      font-size: 13px;
      font-weight: 800;
      color: rgba(0,0,0,.75);
      text-transform: uppercase;
    }

    .icesee-nav a {
      display: block;
      padding: 8px 10px;
      margin: 2px 0;
      border-radius: 8px;
      color: #1f3b64;
      text-decoration: none;
      font-weight: 500;
    }

    .icesee-nav a:hover {
      background: rgba(13,110,253,.08);
    }

    .icesee-nav a.active {
      background: rgba(13,110,253,.12);
      color: #0d6efd;
      font-weight: 700;
    }

    .icesee-main {
      flex: 1 1 auto;
      min-width: 0;
      padding: 18px;
      box-sizing: border-box;
    }
    </style>

    <div class="icesee-sidebar">
      <h2>ICESEE</h2>

      <div class="icesee-nav">
        <a href="/index.html">Home</a>

        <div class="icesee-nav-group">Getting Started</div>
        <a href="/intro.html">ICESEE on GHUB</a>
        <a href="/quickstart.html">Quickstart</a>
        <a href="/icesee_workflow.html">ICESEE Workflow Overview</a>

        <div class="icesee-nav-group">ICESEE-OnLINE</div>
        <a class="active" href="/voila/render/icesee_jupyter_notebooks/icesee_app.ipynb">ICESEE GUI</a>
        <a href="/icesee_jupyter_notebooks/icesheet_models.html">CryoLauncher</a>

        <div class="icesee-nav-group">Tutorials</div>
        <a href="/icesee_jupyter_notebooks/run_lorenz96_da.html">Tutorial: Lorenz-96</a>

        <div class="icesee-nav-group">Deployment Notes</div>
        <a href="/running_with_containers.html">Running with Containers</a>
        <a href="/icesee_hpc_coupling.html">ICESEE-HPC Coupling</a>
        <a href="/user_manual.html">User Manual</a>
      </div>
    </div>
    """
    return W.HTML(sidebar_html)

back_link = W.HTML("""
<style>
.icesee-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 14px;
  color: #0d6efd;
  text-decoration: none;
  transition: color 0.15s ease, transform 0.15s ease;
}

.icesee-back:hover {
  color: #0b5ed7;
  transform: translateX(-1px);
}

.icesee-back-wrap {
  margin-bottom: 14px;
}
</style>

<div class="icesee-back-wrap">
  <a href="https://cryostack.eas.gatech.edu/index.html#" class="icesee-back">
    ← Back to CryoStack Home
  </a>
</div>
""")

session_bridge = W.HTML("""
<script>
(async () => {
    try {
        const response = await fetch("/api/v1/me", {
            credentials: "same-origin",
            cache: "no-store"
        });

        if (!response.ok) {
            return;
        }

        /*
         * We cannot read the HttpOnly session cookie from JavaScript.
         * Therefore this bridge intentionally does not expose credentials.
         */
    } catch (error) {
        console.error("CryoStack session bridge failed:", error);
    }
})();
</script>
""")

app_menu = build_icesheets_app_menu()
shared_styles = shared_application_styles()

def build_backend_check_cmd(backend: str, model: str, remote_base: str, remote_tag: str) -> str:
    root = f"{remote_base.rstrip('/')}/{remote_tag}"
    spack_path = f"{remote_base.rstrip('/')}/ICESEE-Spack"
    container_dir = f"{root}/ICESEE-Containers/spack-managed/combined-container"
    sif_path = f"{container_dir}/combined-env.sif"

    return get_model_adapter(model).build_environment_check(
        spack_path=spack_path,
        sif_path=sif_path,
        backend=backend,
    )

def _agent_mode_enabled() -> bool:
    """Agent is a third interaction mode only when opted in -- otherwise the
    mode selector is exactly Basic / Advanced and nothing agent-related is
    built or shown."""
    return os.environ.get("CRYOSTACK_AGENT_PANEL", "").strip().lower() in (
        "1", "true", "yes", "on")


def _build_agent_panel(workspace_manager):
    """Construct the Run Assistant (Beta) panel for the IceSheets gateway's
    **Agent** interaction mode.

    * context: the authenticated CryoStack user, hard-capped at PLAN, scoped to
      this gateway's ``workspace_manager``;
    * assistant: the deterministic ``RuleBasedAdapter`` (no network / no key)
      unless a provider adapter is wired elsewhere;
    * on_approve: records + persists a digest-bound ``Approval`` in the user's
      own ``AgentStore``. There is no submit step -- no ``SubmitBackend`` is
      wired -- so an approved plan simply waits.

    Agent mode orchestrates the *same* CryoStack services as Basic / Advanced:
    the plan converges on the existing working-copy + validation (B3/B4/
    Basic-mode/preflight) + approval boundary. No parallel execution path.
    """
    from cryostack_src.agents import (
        AgentStore, Permission, RuleBasedAdapter, RunAssistant, RunPlan,
        build_tool_context,
    )
    from cryostack_src.workspace.identity import resolve_workspace_user
    from icesee_jupyter_book.ui.shared_agent_panel import build_agent_panel

    def _context():
        return build_tool_context(
            application="icesheets", max_permission=Permission.PLAN,
            workspace_manager=workspace_manager)

    def _on_approve(plan_dict: dict) -> str:
        user = resolve_workspace_user(require_authenticated=True)
        store = AgentStore(user=user)
        mp = store.plans.create(RunPlan.from_dict(plan_dict))
        mp.mark_validated(mp.plan)
        mp.submit_for_approval()
        # bind the approval to the *content* of the example / run-target /
        # datasets, not just the intent digest, so a later edit blocks a run.
        fp_digest = ""
        try:
            from cryostack_src.agents.planning_tools import fingerprint_run_inputs
            fp_digest = fingerprint_run_inputs(_context(), plan=plan_dict).get("digest", "")
        except Exception:
            fp_digest = ""            # falls back to intent-only binding
        mp.approve(user, input_fingerprint=fp_digest)
        store.plans.save(mp)
        return mp.plan_id

    return build_agent_panel(
        assistant=RunAssistant(llm=RuleBasedAdapter()),
        build_context=_context,
        on_approve=_on_approve,
    )


def build_icesheets_ui():
    _perf_t0 = _time.perf_counter()
    try:
        load_cryostack_account_assets()
        load_experiment_bridge()

        shared_styles = (
            shared_application_styles()
        )

        experiment_bridge = ExperimentBridge()

        load_workspace_bridge()

        workspace_bridge = WorkspaceBridge(
            persistence=WorkspacePersistenceBridge(),
        )

        # =========================================================
        # State
        # =========================================================

        runtime_state = build_runtime_state()

        # Compatibility aliases while the gateway is migrated.
        STATUS = runtime_state.status
        SESSION = runtime_state.session
        AUTO_TAIL = runtime_state.auto_tail

        # =========================================================
        # Controls
        # =========================================================

        run_settings = build_run_settings_state()

        ui_mode_dd = run_settings.ui_mode
        mode_dd = run_settings.execution_mode
        backend_dd = run_settings.backend
        model_dd = run_settings.model

        # Interaction mode: Basic | Advanced are always present; Agent is a
        # third, deliberately-optional mode only when opted in. Without the
        # opt-in the selector and behaviour are byte-identical to before.
        # The Agent panel itself is built later (needs workspace_manager).
        _agent_mode = _agent_mode_enabled()
        agent_panel = None
        if _agent_mode:
            ui_mode_dd.options = [
                ("Basic", "basic"),
                ("Advanced", "advanced"),
                ("Agent · Beta", "agent"),
            ]

        software_panel = build_software_stack_panel()
        image_panel = build_container_image_panel()

        example_picker = run_settings.example_picker
        example_info = run_settings.example_info
        example_dir = run_settings.example_dir
        exec_dir = run_settings.exec_dir

        advanced_action_dd = run_settings.advanced_action

        file_picker = run_settings.file_picker
        file_editor = run_settings.file_editor
        run_target = run_settings.run_target

        new_example_name = run_settings.new_example_name
        dataset_upload = run_settings.dataset_upload

        container_source = run_settings.container_source
        image_uri = run_settings.image_uri

        def _is_oci_source() -> bool:
            return (
                backend_dd.value == "container"
                and container_source.value in ("docker", "oci")
            )

        def effective_image_uri() -> str:
            """The image reference to submit.

            For a Docker/OCI source this is the curated tested-image reference or
            the advanced user's custom URI; for git / local SIF it is the
            gateway's existing free-text field (``.def`` name / SIF path).
            """
            if _is_oci_source():
                return image_panel.selection().image_uri
            return image_uri.value

        def selected_tested_image_key() -> str | None:
            if _is_oci_source():
                sel = image_panel.selection()
                return sel.tested_key if sel.mode == "tested" else None
            return None

        access_mode_dd = W.Dropdown(
            options=[
                ("CryoStack Connector (recommended)", "connector"),
                ("Direct SSH from server (shared-trust / developer)", "direct"),
                ("Auto", "auto"),
            ],
            value="connector",
            layout=W.Layout(width="100%"),
        )

        results_download_btn = W.Button(
            description="Download results",
            icon="download",
            button_style="success",
        )

        figures_download_btn = W.Button(
            description="Download figures",
            icon="picture-o",
            button_style="success",
        )

        auto_tail_btn = W.ToggleButton(
        value=False,
        description="Auto tail",
        icon="refresh",
        button_style="info",
        )

        connector_panel, refresh_connector = build_connector_panel(mode_dd)
        relay_status = W.HTML("")
        start_connector_session_btn = W.Button(
            description="Create connector session",
            icon="plug",
            button_style="info",
        )

        check_backend_btn = W.Button(
            description="Check backend",
            icon="check-circle",
            button_style="info",
        )

        # -----------------------------
        # Remote controls
        #
        # Ownership:
        #   RESOURCE (from ComputeProfile) : login host, ssh port, partition,
        #                                    wall time -- follow the resource.
        #   USER x RESOURCE / USER         : HPC username, remote directory,
        #                                    Slurm account, notification email --
        #                                    BLANK until B2 persistence. Never
        #                                    inferred from the server $USER.
        #   RUN                            : job name, nodes, tasks, tasks/node,
        #                                    memory, per-run overrides.
        # -----------------------------
        _INITIAL_CLUSTER = "pace"
        _rf = initial_remote_fields(_INITIAL_CLUSTER)

        cluster_name_for_keys = W.Text(
            value=_INITIAL_CLUSTER, placeholder="e.g. pace, ub-ccr, frontera",
            continuous_update=False,   # resource switch on commit, not per keystroke
            layout=W.Layout(width="320px"),
        )
        cluster_host = W.Text(value=_rf["login_host"], placeholder="resource login host", layout=W.Layout(width="320px"))
        cluster_user = W.Text(value=_rf["hpc_username"], placeholder=_rf["username_hint"], layout=W.Layout(width="320px"))
        cluster_port = W.IntText(value=_rf["ssh_port"], layout=W.Layout(width="120px"))

        remote_base_dir = W.Text(value=_rf["remote_directory"], placeholder="your remote working directory (required)", layout=W.Layout(width="320px"))
        remote_tag = W.Text(value="icesheets", layout=W.Layout(width="220px"))

        auth_mode = W.ToggleButtons(
            options=[("Key-only", "key"), ("Bootstrap with password (one-time)", "bootstrap")],
            value="key",
            layout=W.Layout(width="auto", max_width="100%"),
        )

        cluster_password = W.Password(
            value="",
            placeholder="One-time password (not stored)",
            layout=W.Layout(width="320px"),
        )

        bootstrap_btn = W.Button(
            description="Enable passwordless SSH",
            icon="key",
            button_style="warning",
        )

        preview_results_btn = W.Button(
            description="Preview results",
            icon="eye",
            button_style="info",
        )

        slurm_job_name = W.Text(value="ICESHEETS", layout=W.Layout(width="100%"))          # RUN
        slurm_time = W.Text(value=_rf["wall_time"], layout=W.Layout(width="100%"))          # RESOURCE default
        slurm_nodes = W.IntText(value=1, layout=W.Layout(width="100%"))                     # RUN
        slurm_ntasks = W.IntText(value=8, layout=W.Layout(width="100%"))                    # RUN
        slurm_tpn = W.IntText(value=8, layout=W.Layout(width="100%"))                       # RUN
        slurm_part = W.Text(value=_rf["partition"], layout=W.Layout(width="100%"))          # RESOURCE default
        slurm_mem = W.Text(value="64G", layout=W.Layout(width="100%"))                      # RUN
        slurm_account = W.Text(                                                             # USER x RESOURCE -- blank
            value=_rf["slurm_account"],
            placeholder=("Slurm allocation (required for this resource)"
                         if _rf["account_required"] else "Slurm allocation"),
            layout=W.Layout(width="100%"),
        )
        slurm_mail = W.Text(                                                                # USER -- blank
            value=_rf["notification_email"],
            placeholder="notification email (optional)",
            layout=W.Layout(width="100%"),
        )

        connect_btn = W.Button(description="Test SSH", icon="terminal", button_style="info")
        status_btn = W.Button(description="Check status", icon="tasks")
        tail_btn = W.Button(description="Tail log", icon="file-text")
        terminate_btn = W.Button(description="Terminate job", icon="stop", button_style="danger")

        cloud_terminate_btn = W.Button(
            description="Terminate",
            icon="stop",
            button_style="danger",
        )

        # Basic-mode ISSM configuration: a curated, solver-aware, validated panel
        # (replaces the old raw md.<section>.<field> editor).
        md_panel = build_issm_md_panel()
        # Basic-mode Icepack configuration: deliberately minimal (ice temperature,
        # timestep count) -- see cryostack_src/models/icepack/parameters.py.
        icepack_basic_panel = build_icepack_basic_panel()

        def _resolve_cloud_execution():
            """Fresh per-operation credential context for the authenticated
            user: BYO-AWS assumed role (fresh sts:AssumeRole), or developer
            mode (ambient/profile). Never persisted. Raises CloudAccessError
            for a broken BYO connection -- callers fail closed."""
            from cryostack_src.cloud.connect import resolve_cloud_execution

            return resolve_cloud_execution(
                user=workspace_manager.owner,
                region_hint=aws_region.value.strip() or DEFAULT_CLOUD_REGION,
                profile_hint=aws_profile.value.strip() or None,
                # derives job_definition/ecr_repository for whichever model
                # is currently selected -- cryostack-issm / cryostack-icepack
                model=(model_dd.value or "issm").strip().lower(),
            )

        def current_cloud_bridge(*, credentials=None, region=None):
            """A CloudBridge for a cloud operation.

            When ``credentials`` is not supplied and the authenticated user has
            a connected BYO-AWS account, this performs a FRESH sts:AssumeRole
            and binds the bridge to those temporary credentials -- there is no
            fallback to the CryoStack host's ambient credentials for a
            connected account. Developer mode (no connection record) keeps the
            existing profile/ambient bridge.
            """
            selected_run = workspace_manager.selected_run()
            selected_metadata = selected_run.metadata if selected_run and selected_run.execution_mode == "cloud" else {}
            if credentials is None:
                _ex = _resolve_cloud_execution()          # may raise CloudAccessError
                if getattr(_ex, "is_byo", False):
                    credentials = _ex.credentials
                    region = region or _ex.region
            return CloudBridge(
                provider="aws",
                region=(
                    region
                    or selected_metadata.get("region")
                    or aws_region.value.strip()
                    or DEFAULT_CLOUD_REGION
                ),
                profile=(
                    None if credentials else (
                        selected_metadata.get("profile")
                        or aws_profile.value.strip()
                        or None
                    )
                ),
                credentials=credentials,
                results_sync=workspace_manager.sync_cloud_results,
            )

        # -- Cloud run state chip: Not configured -> Checking -> Ready ->
        #    Submitting -> Queued -> Running -> Completed / Failed --------
        _CLOUD_STATES = {
            "not_configured": ("icesee-idle", "Not configured"),
            # AWS ACCOUNT has a connection record but it is not yet verified
            # (the user started onboarding, or a page reload found a pending
            # attempt) -- distinct from "nothing configured at all".
            "connection_required": ("icesee-running", "Connection required"),
            # the last verification attempt failed (bad/forgotten Role ARN,
            # AssumeRole denied, account mismatch, ...). The AWS ACCOUNT block
            # carries Retry connection / Change AWS account -- this is never
            # a dead end.
            "connection_issue": ("icesee-fail", "Connection issue"),
            "checking": ("icesee-running", "Checking…"),
            "testing": ("icesee-running", "Testing connection…"),
            "preparing": ("icesee-running", "Preparing…"),
            "smoke_testing": ("icesee-running", "Testing infrastructure…"),
            "connected": ("icesee-done", "Connected"),
            "ready": ("icesee-done", "Ready"),
            "staging": ("icesee-running", "Staging…"),
            "submitting": ("icesee-running", "Submitting…"),
            "queued": ("icesee-running", "Queued"),
            "running": ("icesee-running", "Running"),
            "completed": ("icesee-done", "Completed"),
            "failed": ("icesee-fail", "Failed"),
            "cancelled": ("icesee-idle", "Cancelled"),
        }

        def _set_cloud_state(kind: str) -> None:
            cls, label = _CLOUD_STATES.get(kind, _CLOUD_STATES["not_configured"])
            cloud_state_chip.value = (
                f"<span class='icesee-status {cls}'>Cloud: {label}</span>"
            )
            if kind == "completed":
                status_chip.value = status_html("done")
            elif kind in ("failed", "cancelled"):
                status_chip.value = status_html("fail")

        #: late-bound; assigned once the CloudRunController is built (below).
        _cloud = {"controller": None}

        def _cloud_matlab_license_configured() -> bool:
            """True when the connected BYO account has an ISSM cloud MATLAB
            license mechanism configured (a Secrets Manager ARN). Non-secret;
            the license value never reaches CryoStack. Fail closed."""
            try:
                return bool(_resolve_cloud_execution().matlab_license.configured)
            except Exception:  # noqa: BLE001
                return False

        def _default_tested_image(model: str):
            """The CryoStack tested container image for ``model`` (what Prepare
            Cloud mirrored into ECR). Deterministic; no AWS call."""
            try:
                from cryostack_src.models.stack import default_tested_image_for_model

                return default_tested_image_for_model((model or "").strip().lower())
            except Exception:  # noqa: BLE001
                return None

        def _cloud_container_provenance(handle):
            """Reuse the SAME container/software provenance schema the Remote
            container path records (manifest schema v2), anchored to the exact
            tested-image key frozen on the handle at submit -- so a cloud run's
            recorded image never drifts when CryoStack's default image
            changes. Returns ``(container, software)`` (``{}, {}`` if there is
            no tested image, e.g. developer mode)."""
            key = getattr(handle, "image_key", "") or ""
            if not key:
                return {}, {}
            try:
                from cryostack_src.models.stack import resolve_stack

                resolved = resolve_stack(
                    model=(handle.model or "").strip().lower(),
                    profile="tested", selections=None,
                    container_source="docker", image_uri="",
                    tested_image_key=key, digest_resolver=None,
                )
                return (resolved.get("container") or {},
                        resolved.get("software") or {})
            except Exception as _prov_err:  # noqa: BLE001 - never block a real run
                with log_out:
                    print("[cloud][provenance] (non-fatal)",
                          type(_prov_err).__name__, _prov_err)
                return {}, {}

        def _register_cloud_run(*, handle, result):
            """Enter a submitted cloud run into the experiment/workspace system --
            the same registration the Remote path uses."""
            meta = getattr(result, "metadata", {}) or {}
            s3_run = handle.s3_run
            s3_outputs = meta.get("s3_outputs") or (
                f"{s3_run.rstrip('/')}/outputs" if s3_run else None
            )
            STATUS["batch_job_id"] = handle.job_id
            STATUS["cloud_run"] = s3_run
            _container, _software = _cloud_container_provenance(handle)
            workspace_bridge.start_run(
                name=str(handle.run_id or handle.job_id),
                model=handle.model,
                backend="aws",
                execution_mode="cloud",
                jobid=handle.job_id,
                remote_directory=Path(str(s3_run)),
                log_file=None,
                metadata={
                    **(handle.metadata or {}),
                    "cloud_run": s3_run,
                    "s3_outputs": s3_outputs,
                    "run_id": handle.run_id,
                    "region": handle.region,
                    "job_queue": meta.get("job_queue"),
                    "job_definition": meta.get("job_definition"),
                    "provider": "aws",
                    # C7.5: non-secret -- lets a page refresh re-check this run
                    # with a fresh AssumeRole for the right account. No STS
                    # credentials are ever persisted.
                    "account_id": getattr(handle, "account_id", "") or "",
                    "example": getattr(handle, "example", "") or "",
                    "run_target": getattr(handle, "run_target", "") or "",
                    "source": getattr(handle, "source", "") or "",
                    "vcpu": getattr(handle, "vcpu", 0) or 0,
                    "memory_gib": getattr(handle, "memory_gib", 0) or 0,
                    "expected_runtime_minutes": getattr(
                        handle, "expected_runtime_minutes", 0) or 0,
                    "cost_estimate": getattr(handle, "cost_public", {}) or {},
                    # exact image this run used -- also in metadata so the
                    # CLOUD RUN card can restore it on a page-refresh reattach
                    "image_key": getattr(handle, "image_key", "") or "",
                    "image_label": getattr(handle, "image_label", "") or "",
                    "image_reference": getattr(handle, "image_reference", "") or "",
                    "image_digest": getattr(handle, "image_digest", "") or "",
                    # non-secret AWS resource identity -- seeded now, grown by
                    # each DescribeJobs poll (see _persist_cloud_resources)
                    "aws_resources": dict(getattr(handle, "aws_resources", {}) or {}),
                },
                container=_container,
                software=_software,
            )

        def _icepack_cloud_postprocess_files() -> dict:
            """Icepack's cloud output-collector, staged as an ordinary file
            alongside run.py -- never embedded into the Batch runner script.
            See cryostack_src/cloud/runtime.py's execution-artifact contract."""
            from cryostack_src.cloud.runtime import icepack_postprocess_extra_files

            return icepack_postprocess_extra_files()

        def _submit_cloud_run(staged_dir, md_provenance, *, review=None):
            """Validate + preflight + stage the user-owned working copy
            (synchronous, local, fast), then hand the run to the
            CloudRunController -- staging to S3, submit-job, polling and result
            retrieval all run off the event loop. Never billable on a config
            error.

            When ``review`` (a CloudRunReview from Review & Launch) is given,
            **its** ``config`` is the run configuration -- no second
            CloudRunConfig is built -- and its drift digest + launch gate are
            re-checked here so a change since Review cannot launch.
            """
            _model = model_dd.value
            _jd_warnings: list[str] = []
            if review is not None:
                # the reviewed config IS the run config
                if not review.can_launch:
                    status_chip.value = status_html("fail")
                    _set_cloud_state("failed")
                    with log_out:
                        print("[cloud][ERROR] The reviewed run is blocked:")
                        for _r in review.blocked_reasons:
                            print("  -", _r)
                    return None
                if _cloud_review_digest() != review.digest:
                    status_chip.value = status_html("fail")
                    _set_cloud_state("failed")
                    with log_out:
                        print("[cloud][ERROR] The run configuration changed since "
                              "you reviewed it. Open Review & Launch again.")
                    return None
                _cfg = review.config
            else:
                _job_def, _jd_warnings = resolve_job_definition(
                    _model, batch_job_def.value.strip(), allow_list=_CLOUD_JOB_DEFS,
                )
                _cfg = resolve_cloud_config(
                    provider="aws",
                    region=aws_region.value.strip(),
                    bucket=cloud_bucket.value.strip(),
                    profile=aws_profile.value.strip(),
                    model=_model,
                    job_queue=batch_job_queue.value.strip(),
                    job_definition=_job_def,
                )
            _lic = _cloud_matlab_license_configured()
            _problems = validate_cloud_config(_cfg, model=_model)
            _problems += cloud_run_preflight(
                model=_model, matlab_license_configured=_lic
            )
            if _problems:
                status_chip.value = status_html("fail")
                _set_cloud_state("failed")
                with log_out:
                    print("[cloud][ERROR] Fix the cloud configuration before submitting:")
                    for _p in _problems:
                        print("  -", _p)
                return None

            _target = (Path(run_target.value or "runme.m").name) or "runme.m"
            # the canonical example SOURCE, recorded distinctly from the
            # executable run target (a converted Icepack notebook: source is
            # the .ipynb, run target is run.py). "" when they are the same.
            _sel_path = Path(STATUS.get("selected_example_path") or example_dir.value or "")
            _source = _sel_path.name if _sel_path.suffix.lower() == ".ipynb" else ""

            # cloud always uploads a user-owned working copy (parity with Remote)
            if str(staged_dir) == str(example_dir.value):
                try:
                    _sc = workspace_manager.stage_example_for_run(
                        source_example=example_dir.value,
                        # Icepack: stage the output collector as an ACTUAL
                        # FILE alongside run.py -- never embedded into the
                        # Batch runner script itself (see cloud/runtime.py's
                        # execution-artifact contract; this is what fixed
                        # "Container Overrides length must be at most 8192").
                        extra_files=(
                            _icepack_cloud_postprocess_files()
                            if _model == "icepack" else None
                        ),
                    )
                    staged_dir = str(_sc.path)
                except Exception as _e:
                    status_chip.value = status_html("fail")
                    _set_cloud_state("failed")
                    with log_out:
                        print("[cloud][stage][ERROR]", type(_e).__name__, _e)
                    return None

            with log_out:
                for _w in _jd_warnings:
                    print("[cloud]", _w)
                print(cloud_run_plan_summary(
                    model=_model, region=_cfg.region, bucket=_cfg.bucket,
                    job_queue=_cfg.job_queue, job_definition=_cfg.job_definition,
                ))

            status_chip.value = status_html("running")
            # the tested container image this run executes in -- frozen into
            # the run's provenance at submit so a historical run always shows
            # the image it ACTUALLY used, even after the default changes.
            _img = _default_tested_image(_model)
            _submit_extra = {
                "_image_key": getattr(_img, "key", "") or "",
                "_image_label": getattr(_img, "label", "") or "",
                "_image_reference": getattr(_img, "reference", "") or "",
                "_image_digest": getattr(_img, "digest", "") or "",
            }
            if review is not None:
                _submit_extra.update({
                    "_account_id": review.account_id,
                    "_example": review.example,
                    "_vcpu": review.vcpu,
                    "_memory_gib": review.memory_gib,
                    "_expected_runtime_minutes": review.expected_runtime_minutes,
                    "_cost_public": review.cost.to_public_dict(),
                    "_review_digest": review.digest,
                })
                # prefer the exact image the review resolved (identical here,
                # but keeps submit anchored to what the user reviewed)
                if getattr(review, "image_reference", ""):
                    _submit_extra.update({
                        "_image_key": review.image_key,
                        "_image_label": review.image_label,
                        "_image_reference": review.image_reference,
                        "_image_digest": review.image_digest,
                    })
            _cloud["controller"].submit(
                staged_source=str(staged_dir),
                model=_model,
                run_target=_target,
                bucket=_cfg.bucket,
                run_prefix=(
                    (f"{_cfg.base_prefix.strip('/')}/" if _cfg.base_prefix else "")
                    + user_run_prefix(workspace_manager.owner.safe_id)
                ),
                job_queue=_cfg.job_queue,
                job_definition=_cfg.job_definition,
                job_name=(batch_job_name.value.strip() or "cryostack"),
                matlab_license_configured=_lic,
                _region=_cfg.region,
                _profile=_cfg.profile,
                _md_provenance=md_provenance,
                _source=_source,
                **_submit_extra,
            )
            return None

        def current_remote_bridge(*, mode=None):
            return RemoteBridge(
                mode=mode or access_mode_dd.value,
                host=cluster_host.value.strip(),
                user=cluster_user.value.strip(),
                port=int(cluster_port.value),
                session_id=SESSION.get("id"),
                cluster_name=cluster_name_for_keys.value or "pace",
                direct_submitter=submit_remote_icesheets,
                connector_submitter=submit_remote_icesheets_via_connector,
            )

        def current_experiment_configuration() -> dict:
            return {
                "user_mode": ui_mode_dd.value,
                "execution_mode": mode_dd.value,

                "backend": backend_dd.value,
                "model": model_dd.value,

                "example": (
                    example_picker.value or ""
                ),

                "example_directory": (
                    example_dir.value.strip()
                ),

                "execution_directory": (
                    exec_dir.value.strip()
                ),

                "run_target": (
                    run_target.value or ""
                ),

                "access_mode": (
                    access_mode_dd.value
                ),

                "cluster": {
                    "name": (
                        cluster_name_for_keys.value
                        or ""
                    ),
                    "host": (
                        cluster_host.value.strip()
                    ),
                    "port": int(
                        cluster_port.value
                    ),
                },

                "slurm": {
                    "job_name": (
                        slurm_job_name.value
                    ),
                    "time": (
                        slurm_time.value
                    ),
                    "nodes": int(
                        slurm_nodes.value
                    ),
                    "tasks": int(
                        slurm_ntasks.value
                    ),
                    "tasks_per_node": int(
                        slurm_tpn.value
                    ),
                    "partition": (
                        slurm_part.value
                    ),
                    "memory": (
                        slurm_mem.value
                    ),
                },

                "issm_md": (
                    md_panel.overrides()
                    if model_dd.value == "issm"
                    else {}
                ),
            }

        def show_connector_public_key_help():
            if not SESSION.get("id"):
                create_or_refresh_connector_session()

            result = connector_get_public_key(
                SESSION["id"],
                cluster_name=cluster_name_for_keys.value or "pace",
                hpc_username=cluster_user.value.strip(),
                host=cluster_host.value.strip(),
            )

            with log_out:
                print()
            #     print("[ssh] Automatic key installation did not complete.")
            #     print("[ssh] Some clusters require SSH keys to be added through a web portal.")
            #     print()
            #     print("[ssh] Copy this public key and add it to the cluster SSH key portal:")
            #     print()
            #     print(result.get("public_key_text", "").strip())
            #     print()
            #     print("[ssh] After adding the key, return here and click Test SSH.")
            #     print("[ssh] Then continue using Key-only mode.")

            return result

        def _bootstrap_panel(state, detail=""):
            try:
                remote_conn_panel.set_bootstrap_state(state, detail)
            except (NameError, AttributeError):
                pass

        def on_bootstrap_keys(_=None):
            log_out.clear_output()
            status_chip.value = status_html("running")

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)
            password = cluster_password.value

            if not host or not user:
                status_chip.value = status_html("fail")
                _bootstrap_panel("connector_failed", "Provide Host + HPC username first.")
                with log_out:
                    print("[auth][ERROR] Provide Host + User first.")
                return

            if not password:
                status_chip.value = status_html("fail")
                _bootstrap_panel("password_failed", "Enter your HPC password (used once, never stored).")
                with log_out:
                    print("[auth][ERROR] Enter your password. It is used once and not stored.")
                return

            # Immediate feedback: the button must never look inert.
            bootstrap_btn.disabled = True
            _bootstrap_panel("registering")

            try:
                use_connector = should_use_connector()

                if use_connector:
                    if not SESSION.get("id"):
                        create_or_refresh_connector_session()

                    st = relay_check_status(SESSION["id"], force=True)
                    if not st.get("online"):
                        status_chip.value = status_html("fail")
                        _bootstrap_panel("connector_failed",
                                         "The CryoStack Connector is not connected. "
                                         "Pair it, then try again.")
                        with log_out:
                            print("[connector][ERROR] Connector session is not online.")
                        return

                result = bootstrap_passwordless_ssh(
                    host=host,
                    user=user,
                    port=port,
                    password=password,
                    access_mode="connector" if use_connector else "direct",
                    session_id=SESSION.get("id"),
                    cluster_name=cluster_name_for_keys.value or "pace",
                )

                # scrub the password from the widget the moment the call returns
                cluster_password.value = ""

                with log_out:
                    for msg in result.get("messages", []):
                        print(msg)
                    if (result.get("stdout") or "").strip():
                        print("--- stdout ---"); print(result["stdout"].strip())
                    if (result.get("stderr") or "").strip():
                        print("--- stderr ---"); print(result["stderr"].strip())

                verdict = classify_bootstrap_result(result)
                if verdict == "installed":
                    status_chip.value = status_html("done")
                    auth_mode.value = "key"
                    _bootstrap_panel("verifying")
                    with log_out:
                        print("[auth] Public key installed on the resource — verifying access…")
                    # The real B3 identity check decides Verified / mismatch / failed.
                    try:
                        on_test_remote(None)
                    except Exception as _e:
                        _bootstrap_panel("connector_failed")
                        with log_out:
                            print("[auth] re-check skipped:", type(_e).__name__, _e)
                else:
                    status_chip.value = status_html("fail")
                    _bootstrap_panel(verdict)
                    with log_out:
                        print(f"[auth] bootstrap did not complete (reason: "
                              f"{result.get('reason') or verdict}).")

            except Exception as e:
                cluster_password.value = ""
                status_chip.value = status_html("fail")
                _bootstrap_panel("timed_out" if "timeout" in type(e).__name__.lower()
                                 else "connector_failed")
                with log_out:
                    print("[auth][ERROR]", type(e).__name__, e)
            finally:
                bootstrap_btn.disabled = False
                cluster_password.value = ""     # never persisted/logged

        def create_or_refresh_connector_session(_=None):
            log_out.clear_output()

            try:
                # A relay-side session that is gone/expired/superseded must be
                # recreated, not reused -- otherwise commands fail closed later.
                if SESSION.get("id"):
                    prior = relay_check_status(SESSION["id"], force=True)
                    if prior.get("state") in {"unknown", "expired", "superseded"}:
                        SESSION.clear()

                if SESSION.get("id") is None:
                    owner = resolve_workspace_user(require_authenticated=True)
                    sess = create_session(owner_user_id=owner.user_id)
                    SESSION["id"] = sess["session_id"]
                    SESSION["ws_url"] = sess["ws_url"]
                    SESSION["pairing_code"] = sess["pairing_code"]

                    connector_setup_link.value = f"""
                    <a href="https://cryostack.eas.gatech.edu/connect/?session={SESSION['id']}&app=icesheets"
                    target="_blank"
                    style="
                        display:inline-block;
                        background:#0d6efd;
                        color:white;
                        padding:8px 12px;
                        border-radius:8px;
                        text-decoration:none;
                        font-weight:700;
                        margin:6px 0;">
                    Open CryoStack Connector Setup
                    </a>
                    """

                st = relay_check_status(SESSION["id"])
                online = bool(st.get("online"))

                relay_status.value = f"""
                <div style="
                    border:1px solid {'rgba(25,135,84,.25)' if online else 'rgba(13,110,253,.18)'};
                    background:{'rgba(25,135,84,.08)' if online else 'rgba(13,110,253,.06)'};
                    border-radius:12px; padding:12px; line-height:1.6; margin:8px 0;
                ">
                  <b>Connector:</b> {'connected ✅' if online else 'waiting for connector'}<br>
                  <b>Pairing code:</b>
                  <code style="font-size:15px;background:#eef1f4;padding:2px 8px;border-radius:6px;">
                  {SESSION.get('pairing_code', '—')}</code><br>
                  <span style="color:#5f6b7a;font-size:13px;">
                  Enter this code in the CryoStack Connector on your workstation
                  (“Pair with CryoStack…”). It is one-time and expires with this session.
                  </span>
                  <details style="margin-top:8px;">
                    <summary style="cursor:pointer;color:#5f6b7a;font-size:13px;">Diagnostics</summary>
                    <div style="font-size:12px;color:#5f6b7a;margin-top:4px;">
                      session id: {SESSION['id']}<br>
                      ws path: {SESSION['ws_url']}<br>
                      relay state: {st.get('state', 'unknown')}
                    </div>
                  </details>
                </div>
                """

                with log_out:
                    print("[connector] pairing code:", SESSION.get("pairing_code"))
                    print("[connector] relay state:", st.get("state"))

            except Exception as e:
                relay_status.value = ""
                with log_out:
                    print("[connector][ERROR]", type(e).__name__, e)

        # Cloud controls
        # -----------------------------
        cloud_environment = build_cloud_environment_card(
            region=DEFAULT_CLOUD_REGION,
            profile="",
            s3_prefix="",
            job_queue="",
            job_definition="",
            job_name="cryostack",
        )

        cloud_state_chip = W.HTML(
            "<span class='icesee-status icesee-idle'>Cloud: Not configured</span>"
        )
        cloud_box = W.VBox(
            [cloud_state_chip, cloud_environment.container],
            layout=W.Layout(width="100%", gap="8px"),
        )

        aws_region = cloud_environment.region
        aws_profile = cloud_environment.profile
        cloud_bucket = cloud_environment.s3_prefix
        batch_job_queue = cloud_environment.job_queue
        batch_job_def = cloud_environment.job_definition
        batch_job_name = cloud_environment.job_name

        cloud_status_btn = W.Button(description="Check status", icon="search")
        cloud_logs_btn = W.Button(description="Logs hint", icon="file-text")
        cloud_smoke_btn = W.Button(
            description="Infrastructure smoke test", icon="stethoscope")

        # =========================================================
        # Outputs
        # =========================================================

        summary_html = W.HTML()

        command_preview = W.Textarea(
            layout=W.Layout(
                width="100%",
                height="130px",
            )
        )

        connector_setup_link = W.HTML("")

        # The Run Log viewer: a useful minimum height, grows with the log, then
        # scrolls internally once it reaches the usable viewport bottom (cap set
        # by the scoped viewer-sizing script; relaxed on narrow screens).
        log_out = W.Output(
            layout=W.Layout(
                width="100%",
                min_height="280px",
                overflow_y="auto",
                overflow_x="auto",
                border="1px solid rgba(0,0,0,.10)",
                padding="10px",
            )
        )

        results_out = W.Output(
            layout=W.Layout(
                width="100%",
                min_height="0",
                overflow_y="auto",
                overflow_x="auto",
                border="1px solid rgba(0,0,0,.10)",
                padding="10px",
            )
        )

        log_out.add_class("cryostack-live-log")
        log_out.add_class("cryostack-log-viewer")
        results_out.add_class("cryostack-live-log")

        # Log auto-scroll / live-tail follow is handled by the Workspace
        # viewer-sizing module (workspace/viewer_geometry.js, mounted via
        # build_workspace_explorer) -- it follows the tail while the user is at
        # the bottom and offers "Jump to latest" once they scroll up.
        auto_scroll_script = W.HTML("")

        # =========================================================
        # Helpers
        # =========================================================
        def form_row(label: str, widget):
            lbl = W.HTML(f"<div class='icesee-lbl'>{label}</div>")
            lbl.layout = W.Layout(width="120px", min_width="120px")
            return W.HBox([lbl, widget], layout=W.Layout(gap="10px", width="100%"))

        def form_pair(label: str, widget, label_width: str = "80px"):
            lbl = W.HTML(f"<div class='icesee-lbl'>{label}</div>")
            lbl.layout = W.Layout(width=label_width, min_width=label_width)
            row = W.HBox([lbl, widget], layout=W.Layout(gap="10px", width="100%"))
            row.add_class("cryostack-field-row")
            return row

        def selected_text(dd: W.Dropdown) -> str:
            for label, value in dd.options:
                if value == dd.value:
                    return label
            return str(dd.value)
        
        def _discover_examples():
            model = model_dd.value
            adapter = get_model_adapter(model)
            return merged_examples_for_model(
                model,
                user_examples=workspace_manager.list_user_examples(model),
                runnable_check=getattr(adapter, "example_runnable", None),
            )

        def refresh_example_picker(_=None, *, select: str | None = None):
            examples = _discover_examples()
            opts = [(ex.label, str(ex.path)) for ex in examples]
            if not opts:
                example_picker.options = [("(no examples found)", "")]
                example_picker.value = ""
                example_info.value = "No examples were discovered for this model."
                if ui_mode_dd.value == "basic":
                    example_dir.value = ""
                STATUS["selected_example_path"] = None
                update_summary()
                return

            values = [v for _l, v in opts]
            keep = select if select in values else (
                example_picker.value if example_picker.value in values else values[0]
            )
            example_picker.options = opts
            example_picker.value = keep

        _editor_ctx = {"last_example": "", "last_model": model_dd.value}

        def apply_selected_example(_=None):
            selected = example_picker.value or ""
            if selected == _editor_ctx["last_example"]:
                return
            # never discard unsaved editor work on an example / model switch
            if not editor_panel.controller.guard_context_switch():
                example_picker.value = _editor_ctx["last_example"]
                return
            _editor_ctx["last_example"] = selected

            STATUS["selected_example_path"] = selected or None

            ex = None
            if selected:
                ex = next((e for e in _discover_examples()
                           if str(e.path) == selected), None)
            example_info.value = _example_summary(ex, selected)

            _materialized_entrypoint = None      # e.g. "run.py" -- set below
            if selected:
                _selected_path = Path(selected)
                if model_dd.value == "icepack" and _selected_path.is_file():
                    # A canonical Icepack example is one loose notebook FILE
                    # (there is no "example directory" the way ISSM has) --
                    # materialize the SAME deterministic {notebook, run.py}
                    # working copy staging itself uses (workspace/manager.py
                    # :meth:`stage_example_for_run`), so the Advanced Editor
                    # shows the runnable Python representation -- not raw
                    # notebook JSON -- and every downstream consumer
                    # (run-target resolution, Local/Remote/Cloud staging)
                    # sees an ordinary example directory from here on.
                    try:
                        _staged = workspace_manager.stage_example_for_run(
                            source_example=selected
                        )
                        example_dir.value = str(_staged.path)
                        _materialized_entrypoint = _staged.provenance.get("entrypoint")
                    except NotebookConversionError as _conv_err:
                        example_dir.value = selected
                        with log_out:
                            print("[icepack][ERROR]", _conv_err)
                    except Exception as _conv_err:                  # noqa: BLE001
                        example_dir.value = selected
                        with log_out:
                            print(
                                "[stage][ERROR] Could not prepare this notebook "
                                "example:", type(_conv_err).__name__, _conv_err,
                            )
                else:
                    example_dir.value = selected

            editor_panel.controller.refresh()
            refresh_run_target_options()

            # reset auto-target when example changes
            run_target.value = ""
            auto_set_run_target()

            if _materialized_entrypoint:
                # A fresh example selection only -- editor_panel.controller
                # .refresh() itself always keeps whatever file the user
                # already has open across a plain Refresh (its own
                # prev-file/prev-name preservation, untouched here), so this
                # can never "unexpectedly" pull an in-progress edit of
                # run.py back to the notebook later. run.py is a generated
                # artifact regenerated on every (re)stage above -- this only
                # steers which already-staged file the editor shows first,
                # it never overwrites the buffer of one already open.
                editor_panel.controller.open_file_by_name(_materialized_entrypoint)

            if model_dd.value == "issm":
                md_panel.set_example(example_dir.value)
            elif model_dd.value == "icepack":
                icepack_basic_panel.set_example(example_dir.value)
            update_summary()

        def _example_summary(ex, selected: str) -> str:
            if ex is None:
                return example_summary_text(None)
            lines = [
                f"Model: {ex.model_name.upper()}",
                f"Name: {Path(selected).name}",
                "Access: your workspace (editable)" if ex.owned
                else "Access: application example (read-only)",
                f"Runnable: {'yes' if ex.runnable else 'no — add a run target'}",
                f"Path: {selected}",
            ]
            if ex.description:
                lines.append(ex.description)
            return "\n".join(lines)

        def build_model_command():
            backend = backend_dd.value
            run_file = selected_run_file()
            run_file_name = Path(run_file).name if run_file else ""
            # Cloud runs are described to AWS Batch by three non-secret env
            # values (see cryostack_src/cloud/drivers/aws/submit.py) -- the
            # generic runner + model command are baked into the job
            # definition, not composed here. Show the submission summary, not
            # a spack / apptainer command that does not apply.
            if mode_dd.value == "cloud":
                _m = (model_dd.value or "issm").strip().lower()
                _img = _default_tested_image(_m)
                _jd, _ = resolve_job_definition(
                    _m, batch_job_def.value.strip(), allow_list=_CLOUD_JOB_DEFS,
                )
                return (
                    "aws batch submit-job \\\n"
                    f"  --job-queue {batch_job_queue.value.strip() or '<derived>'} \\\n"
                    f"  --job-definition {_jd} \\\n"
                    "  --container-overrides '{\"environment\":["
                    "{\"name\":\"CRYOSTACK_MODEL\",\"value\":\"" + _m + "\"},"
                    "{\"name\":\"CRYOSTACK_RUN_TARGET\",\"value\":\""
                    + (run_file_name or 'run.py') + "\"},"
                    "{\"name\":\"CRYOSTACK_S3_RUN\",\"value\":\"s3://<bucket>/runs/<user>/<run-id>\"}]}'\n"
                    f"# image: {getattr(_img, 'reference', '') or '<tested (default)>'}"
                )
            return get_model_adapter(model_dd.value).build_run_command(
                backend=backend,
                target=run_file_name,
                example_dir=example_dir.value,
                exec_dir=exec_dir.value,
                image_uri=effective_image_uri(),
                ntasks=slurm_ntasks.value,
            )
        
        _ws_span = perf.span("workspace manager")
        _ws_span.__enter__()
        workspace_manager = WorkspaceManager(
            owner=resolve_workspace_user(require_authenticated=True),
            status=STATUS,
            session=SESSION,
            example_dir=example_dir,
            model=model_dd,
            backend=backend_dd,
            file_picker=file_picker,
            file_editor=file_editor,
            log_output=log_out,
            results_output=results_out,
            cluster_host=cluster_host,
            cluster_user=cluster_user,
            cluster_port=cluster_port,
            access_mode=access_mode_dd,
            normalize_remote_path=normalize_remote_path,
            connector_fetch_archive=connector_fetch_archive,
            should_use_connector=lambda: should_use_connector(),
            connector_ssh=connector_ssh,
            ssh_run=ssh_run,
            cluster_name=cluster_name_for_keys,
        )
        _ws_span.__exit__(None, None, None)
        workspace_bridge.attach_manager(workspace_manager)

        # Build the Agent-mode panel now that the (per-user) workspace manager
        # exists. Any failure downgrades the selector to Basic / Advanced.
        if _agent_mode and agent_panel is None:
            try:
                agent_panel = _build_agent_panel(workspace_manager)
            except Exception as _ag_err:            # never block the gateway
                with log_out:
                    print("[agent] Agent mode unavailable:",
                          type(_ag_err).__name__, _ag_err)
                agent_panel = None
                _agent_mode = False
                ui_mode_dd.options = [("Basic", "basic"), ("Advanced", "advanced")]

        def list_editable_files(example_path: str) -> list[tuple[str, str]]:
            return workspace_manager.list_editable_files(example_path)

        # Advanced-mode editor: a generic, model-neutral workspace facility.
        editor_panel = build_editor_panel(
            manager=workspace_manager,
            model_value=lambda: model_dd.value,
            example_dir_widget=example_dir,
            log_output=log_out,
            on_files_changed=lambda: refresh_run_target_options(),
            on_clone_created=lambda dest: refresh_example_picker(select=str(dest)),
            on_examples_changed=lambda _action, dest: refresh_example_picker(
                select=str(dest) if dest is not None else None
            ),
            example_template=lambda: (
                getattr(get_model_adapter(model_dd.value), "example_template", lambda: None)()
            ),
        )

        dataset_panel = build_dataset_panel(
            manager=workspace_manager,
            uploader=dataset_upload,
            log_output=log_out,
            current_example_path=lambda: example_dir.value,
        )

        # Deterministic Results visualization (model adapter supplies the
        # renderer; this panel stays a model-neutral selector). ``fetch_results``
        # is late-bound: it dispatches to the backend that produced the run
        # (remote rsync / connector archive / cloud S3 sync) and lands outputs
        # in the one backend-neutral local shape the ResultPackage reads.
        def _visualization_fetch_results():
            return sync_selected_run_results()

        visualization_panel = build_visualization_panel(
            manager=workspace_manager,
            selected_run_id=lambda: (
                workspace_manager.selected_run().id
                if workspace_manager.selected_run() else ""
            ),
            log_output=log_out,
            fetch_results=_visualization_fetch_results,
        )

        def refresh_run_target_options(_=None):
            files = list_editable_files(example_dir.value.strip())
            opts = [Path(v).name for _, v in files if v]
            adapter = get_model_adapter(model_dd.value)
            final_opts = adapter.order_run_targets(opts)
            run_target.options = final_opts

            current = (run_target.value or "").strip()
            if current and current in final_opts:
                return

            run_target.value = adapter.choose_run_target(final_opts)
                
        def auto_set_run_target(_=None):
            current = (run_target.value or "").strip()
            if current:
                return

            opts = list(run_target.options or [])
            if not opts:
                run_target.value = ""
                return

            run_target.value = get_model_adapter(model_dd.value).choose_run_target(opts)

        def selected_run_file() -> str:
            target = (run_target.value or "").strip()
            if not target:
                return ""

            root = current_example_root()
            if root is None:
                return target

            candidate = root / target
            return str(candidate)
        
        def compute_run_target_text() -> str:
            target = (run_target.value or "").strip()
            if not target:
                return "(default environment check)"
            return target

        def current_example_root() -> Path | None:
            return workspace_manager.example_root()

        def on_check_backend(_=None):
            log_out.clear_output()
            status_chip.value = status_html("running")

            cmd = build_backend_check_cmd(
                backend_dd.value,
                model_dd.value,
                remote_base_dir.value,
                remote_tag.value,
            )

            try:
                if should_use_connector():
                    if not SESSION.get("id"):
                        create_or_refresh_connector_session()

                    bridge = current_remote_bridge(mode="connector")
                else:
                    bridge = current_remote_bridge(mode="direct")

                res = bridge.check_backend(command=cmd, timeout=120)
                rc = res.get("returncode", 1)
                out = res.get("stdout", "")
                err = res.get("stderr", "")
                ok = res.get("ok", False)

                with log_out:
                    print("[backend] Check", backend_dd.value, "for", model_dd.value)
                    print("returncode:", rc)
                    if out.strip():
                        print("--- stdout ---")
                        print(out.strip())
                    if err.strip():
                        print("--- stderr ---")
                        print(err.strip())

                status_chip.value = status_html("done" if ok else "fail")

            except Exception as e:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[backend][ERROR]", type(e).__name__, e)


        # =========================================================
        # Dynamic logic
        # =========================================================
        def update_visibility(_=None):
            is_container = backend_dd.value == "container"
            is_oci = is_container and container_source.value in ("docker", "oci")

            container_source.layout.display = "" if is_container else "none"
            image_uri.layout.display = "" if (is_container and not is_oci) else "none"
            image_panel.set_visible(is_oci)

            spack_enable.layout.display = "none" if is_container else ""
            spack_repo_url.layout.display = "none" if is_container else ""
            spack_dirname.layout.display = "none" if is_container else ""
            spack_install_if_needed.layout.display = "none" if is_container else ""
            spack_install_mode.layout.display = "none" if is_container else ""
            # spack_slurm_dir.layout.display = "none" if is_container else ""
            # spack_pmix_dir.layout.display = "none" if is_container else ""

            is_remote = mode_dd.value == "remote"
            is_cloud = mode_dd.value == "cloud"
            is_agent = ui_mode_dd.value == "agent"
            is_basic = ui_mode_dd.value == "basic" or (not is_agent and not
                                                       ui_mode_dd.value == "advanced")
            is_advanced = ui_mode_dd.value == "advanced"

            # Agent is a peer interaction mode: when it is selected, the manual
            # Basic / Advanced configuration is hidden and only the Run
            # Assistant panel + the shared run details (log / results / history)
            # remain. The mode toggle itself stays visible so the user can
            # switch back. No agent controls appear in Basic / Advanced.
            if agent_panel is not None:
                agent_panel.container.layout.display = "" if is_agent else "none"
            _manual = "none" if is_agent else ""

            container_source_row.layout.display = "" if (is_container and not is_agent) else "none"
            image_uri_row.layout.display = "" if (is_container and not is_oci and not is_agent) else "none"

            remote_box.layout.display = "" if (is_remote and not is_agent) else "none"
            cloud_box.layout.display = "" if (is_cloud and not is_agent) else "none"

            remote_actions.layout.display = "" if (is_remote and not is_agent) else "none"
            cloud_actions.layout.display = "" if (is_cloud and not is_agent) else "none"
            # remote_actions = remote_log_controls
            # cloud_actions = cloud_log_controls
            terminate_btn.layout.display = "" if (is_remote and not is_agent) else "none"
            # Cloud mode: the CLOUD RUN card (Terminate / View log / View
            # results, wired to the account-aware CloudRunController) is THE
            # single authoritative run-control surface once a run exists.
            # The generic Execution panel's own Submit job / Terminate here
            # are unconditionally hidden for cloud mode -- never shown, not
            # even the "shown only in cloud mode" state they had before --
            # so a user can never reach a second, non-account-bound path to
            # the same job. Local/Remote are completely unaffected: run_btn
            # keeps its existing (always-on) visibility for those modes, and
            # remote_terminate_button's own toggle above is untouched.
            run_btn.layout.display = "none" if (is_cloud and not is_agent) else ""
            cloud_terminate_btn.layout.display = "none"

            mode_row.layout.display = _manual
            model_row.layout.display = _manual
            example_picker_row.layout.display = _manual
            example_info_row.layout.display = _manual

            example_row.layout.display = "none" if (is_basic or is_agent) else ""
            exec_row.layout.display = _manual

            advanced_action_row.layout.display = "" if (is_advanced and not is_agent) else "none"
            editor_panel.container.layout.display = "" if (is_advanced and not is_agent) else "none"
            run_target_row.layout.display = _manual
            dataset_panel.container.layout.display = "" if (is_advanced and not is_agent) else "none"
            download_buttons_row.layout.display = ""

            md_config_panel.layout.display = "" if (model_dd.value == "issm" and not is_agent) else "none"
            icepack_config_panel.layout.display = "" if (model_dd.value == "icepack" and not is_agent) else "none"

            # the manual Run button + Run Plan belong to Basic / Advanced only
            try:
                actions_card.layout.display = "none" if is_agent else ""
                run_plan.container.layout.display = "none" if is_agent else ""
            except NameError:
                pass

            # A connector session is created lazily -- on the "Open Connector
            # Setup" button, and at Check SSH / Run when connector mode is
            # active -- never during page construction or a mode toggle. That
            # removes a relay HTTP round trip from the initial-load and
            # resource-switch paths (perf pass).

            if is_remote:
                log_runtime_controls.children = (
                    connect_btn,
                    status_btn,
                    tail_btn,
                    # auto_tail_btn,
                    clear_btn,
                )

            elif is_cloud:
                log_runtime_controls.children = (
                    cloud_smoke_btn,
                    cloud_status_btn,
                    cloud_logs_btn,
                    clear_btn,
                )

            else:
                log_runtime_controls.children = (
                    clear_btn,
                )

            update_summary()

        def update_summary(_=None):
            backend = backend_dd.value
            model = model_dd.value
            mode = mode_dd.value
            user_mode = ui_mode_dd.value

            if model == "issm":
                example_dir.placeholder = "~/ISSM/examples/<example_name>"
                exec_dir.placeholder = "~/runs/issm"
            else:
                example_dir.placeholder = "~/icepack/notebooks/tutorials/<example>.ipynb"
                exec_dir.placeholder = "~/runs/icepack"

            selected = STATUS.get("selected_example_path")
            selected_line = ""
            if selected:
                selected_line = f"<div><span class='icesee-summary-k'>Selected example:</span> {selected}</div>"

            def _cloud_source_lines() -> str:
                """Truthful 'what runs' lines for the cloud Run Plan: the
                canonical example SOURCE vs. the executable ARTIFACT.

                A converted Icepack notebook shows the notebook as the source
                and run.py as the run target -- AWS Batch never executes the
                .ipynb (it is nbconvert'd to run.py before staging). ISSM and
                ordinary script examples stay truthful to their own
                source == run-target relationship.
                """
                _p = Path(selected or "")
                _name = _p.stem or _p.name or "example"
                _rt = (run_target.value or "").strip()
                rows = [f"<div><span class='icesee-summary-k'>Example:</span> "
                        f"{html.escape(_name)}</div>"]
                _suffix = _p.suffix.lower()
                if _suffix == ".ipynb":
                    _rt = _rt or "run.py"
                    rows.append(
                        "<div><span class='icesee-summary-k'>Source:</span> "
                        f"<code>{html.escape(_p.name)}</code> "
                        "<span class='icesee-subtle'>(converted to "
                        "<code>run.py</code> before staging)</span></div>")
                elif _suffix:
                    rows.append(
                        "<div><span class='icesee-summary-k'>Source:</span> "
                        f"<code>{html.escape(_p.name)}</code></div>")
                if _rt:
                    rows.append(
                        "<div><span class='icesee-summary-k'>Run target:</span> "
                        f"<code>{html.escape(_rt)}</code> "
                        "<span class='icesee-subtle'>(executed on AWS Batch)</span></div>")
                return "\n".join(rows)

            # Cloud is its own execution mode: the compute substrate is AWS
            # Batch/Fargate and the scientific stack is ALWAYS the tested
            # container image (whose environment is Spack-built) -- backend_dd
            # (spack vs. host-container-bind) does not apply and is not read
            # here. Remote/Local keep the existing spack/container branches
            # below, untouched.
            if mode == "cloud":
                _img = _default_tested_image(model)
                _img_ref = getattr(_img, "reference", "") or ""
                _img_digest = getattr(_img, "digest", "") or ""
                _short = (_img_digest[:22] + "…") if _img_digest.startswith("sha256:") else _img_digest
                _img_line = (
                    f"<div><span class='icesee-summary-k'>Container image:</span> "
                    f"{html.escape(_img_ref) or '<em>tested (default)</em>'}"
                    + (f" <span class='icesee-subtle'>@ {html.escape(_short)}</span>" if _short else "")
                    + "</div>"
                )
                summary_html.value = f"""
                <div class="icesee-summary">
                  <div><span class="icesee-summary-k">User mode:</span> {user_mode.title()}</div>
                  <div><span class="icesee-summary-k">Execution mode:</span> Cloud</div>
                  <div><span class="icesee-summary-k">Cloud backend:</span> AWS Batch (Fargate)</div>
                  <div><span class="icesee-summary-k">Model environment:</span> ICESEE-Container (Spack-built stack)</div>
                  <div><span class="icesee-summary-k">Model:</span> {model.upper()}</div>
                  {_img_line}
                  {_cloud_source_lines()}
                  <div><span class="icesee-summary-k">Execution:</span> Runs the tested combined image on AWS Batch/Fargate; run inputs and outputs sync via S3.</div>
                </div>
                """
                command_preview.value = build_model_command()
                return

            if backend == "spack":
                if model == "issm":
                    model_root = "ICESEE-Spack/.icesee-spack/externals/ISSM"
                    exec_note = "Use the native ISSM workflow inside the ICESEE-Spack environment."
                else:
                    model_root = "ICESEE-Spack/icepack"
                    exec_note = "Use the native Icepack workflow inside the ICESEE-Spack environment."

                summary_html.value = f"""
                <div class="icesee-summary">
                  <div><span class="icesee-summary-k">User mode:</span> {user_mode.title()}</div>
                  <div><span class="icesee-summary-k">Execution mode:</span> {mode.title()}</div>
                  <div><span class="icesee-summary-k">Backend:</span> ICESEE-Spack</div>
                  <div><span class="icesee-summary-k">Model:</span> {model.upper()}</div>
                  <div><span class="icesee-summary-k">Model root:</span> {model_root}</div>
                  {selected_line}
                  <div><span class="icesee-summary-k">Execution:</span> {exec_note}</div>
                </div>
                """
            else:
                source_name = {
                    "docker": "Docker / OCI",
                    "local": "Local SIF",
                }.get(container_source.value, "ICESEE-Containers (git)")
                exec_note = (
                    "Create host-side example and execution folders, then bind them into "
                    "the combined ICESEE container before launching the selected model."
                )

                if container_source.value in ("docker", "oci"):
                    sel = image_panel.selection()
                    ti = sel.tested_image
                    if ti is not None:
                        image_lines = (
                            f"<div><span class='icesee-summary-k'>Container image:</span> "
                            f"{html.escape(ti.label)} — Tested</div>"
                            f"<div><span class='icesee-summary-k'>OCI reference:</span> "
                            f"{html.escape(ti.reference)}</div>"
                            f"<div><span class='icesee-summary-k'>Digest:</span> "
                            f"{html.escape(ti.short_digest)}</div>"
                        )
                    else:
                        custom_uri = (sel.custom_uri or "").strip()
                        image_lines = (
                            "<div><span class='icesee-summary-k'>Container image:</span> Custom</div>"
                            f"<div><span class='icesee-summary-k'>OCI reference:</span> "
                            f"{html.escape(custom_uri) or '<em>not set</em>'}</div>"
                            "<div><span class='icesee-summary-k'>Digest:</span> unresolved</div>"
                        )
                else:
                    image_lines = (
                        f"<div><span class='icesee-summary-k'>Image:</span> "
                        f"{html.escape(image_uri.value) or '<em>default</em>'}</div>"
                    )

                summary_html.value = f"""
                <div class="icesee-summary">
                  <div><span class="icesee-summary-k">User mode:</span> {user_mode.title()}</div>
                  <div><span class="icesee-summary-k">Execution mode:</span> {mode.title()}</div>
                  <div><span class="icesee-summary-k">Backend:</span> ICESEE-Container</div>
                  <div><span class="icesee-summary-k">Model:</span> {model.upper()}</div>
                  {selected_line}
                  <div><span class="icesee-summary-k">Image source:</span> {source_name}</div>
                  {image_lines}
                  <div><span class="icesee-summary-k">Execution:</span> {exec_note}</div>
                </div>
                """

            # run_target.value = compute_run_target_text()
            command_preview.value = build_model_command()

        def _guard_model_switch(change):
            # never discard unsaved editor work on a model switch
            if change["new"] == _editor_ctx["last_model"]:
                return
            if not editor_panel.controller.guard_context_switch():
                model_dd.value = _editor_ctx["last_model"]   # revert (re-fires, then no-ops)
                return
            _editor_ctx["last_model"] = change["new"]

        # One coalescing point for the Run Plan / summary refresh: a batch of
        # programmatic .value = ... assignments (resource switch, B2 hydration)
        # rebuilds the summary once at the end instead of once per assignment.
        ui_refresh = UIRefreshCoordinator(on_settle=update_summary)
        _summary = ui_refresh.guard(update_summary)

        backend_dd.observe(update_visibility, names="value")
        model_dd.observe(_guard_model_switch, names="value")   # must precede the reloaders
        model_dd.observe(refresh_example_picker, names="value")
        model_dd.observe(_summary, names="value")
        model_dd.observe(lambda _c: software_panel.set_model(model_dd.value), names="value")
        model_dd.observe(lambda _c: image_panel.set_model(model_dd.value), names="value")
        # the Basic-mode configuration accordion is model-specific
        # (md_config_panel vs. icepack_config_panel -- each with its own
        # "<MODEL> configuration (Basic)" title). update_visibility already
        # toggles which one is shown from model_dd.value; it just was not
        # re-run on a model switch, so the ISSM panel stayed visible with
        # Icepack selected. Runs last so it also picks up any state the
        # software/image panel observers above just changed.
        model_dd.observe(update_visibility, names="value")
        software_panel.observe_profile(lambda profile: image_panel.set_profile(profile))
        image_panel.on_change(update_summary)
        mode_dd.observe(update_visibility, names="value")
        ui_mode_dd.observe(update_visibility, names="value")
        container_source.observe(_summary, names="value")
        image_uri.observe(_summary, names="value")
        example_dir.observe(_summary, names="value")
        exec_dir.observe(_summary, names="value")
        slurm_ntasks.observe(_summary, names="value")

        def _sync_resource_facts(_=None):
            # RESOURCE facts follow the selected resource. Personal fields
            # (username, remote dir, account, email) are never touched here.
            rf = initial_remote_fields(cluster_name_for_keys.value)
            cluster_host.value = rf["login_host"]
            cluster_port.value = rf["ssh_port"]
            cluster_user.placeholder = rf["username_hint"]
            slurm_part.value = rf["partition"]
            slurm_time.value = rf["wall_time"]
            # B4: resource-aware auth options + manual key-registration checklist.
            try:
                remote_conn_panel.apply_profile(
                    get_compute_profile(cluster_name_for_keys.value or "")
                )
            except NameError:
                pass

        # --- B2: authenticated user x resource personal-settings persistence ---
        def _b2_read_personal() -> dict:
            return {
                "hpc_username": cluster_user.value,
                "remote_directory": remote_base_dir.value,
                "account": slurm_account.value,
                "email": slurm_mail.value,
                "access_mode": access_mode_dd.value,
                "auth_mode": auth_mode.value,
            }

        def _b2_apply_personal(s: dict) -> None:
            cluster_user.value = s.get("hpc_username", "") or ""
            remote_base_dir.value = s.get("remote_directory", "") or ""
            slurm_account.value = s.get("account", "") or ""
            slurm_mail.value = s.get("email", "") or ""
            if s.get("access_mode") in {"auto", "direct", "connector"}:
                access_mode_dd.value = s["access_mode"]
            _saved_auth = s.get("auth_mode")
            if _saved_auth in {t for _, t in auth_mode.options}:
                auth_mode.value = _saved_auth

        _b2_load, _b2_save = make_state_io(
            workspace_bridge, "cryolauncher",
            resolve_workspace_user(require_authenticated=False).user_id,
        )
        resource_state = ResourceStateController(
            load_state=_b2_load, save_state=_b2_save,
            read_personal=_b2_read_personal, apply_personal=_b2_apply_personal,
            resource_name=lambda: cluster_name_for_keys.value,
            set_resource_name=lambda n: setattr(cluster_name_for_keys, "value", n),
            service_username=(os.environ.get("USER") or getpass.getuser() or ""),
        )

        def _on_resource_changed(change):
            with ui_refresh.batch():
                resource_state.switch_resource(change.get("old"), change.get("new"))
                _sync_resource_facts()
            ui_refresh.request_refresh()

        cluster_name_for_keys.observe(_on_resource_changed, names="value")
        example_picker.observe(apply_selected_example, names="value")
        # (removed: auto connector-session creation on access-mode change --
        #  the session is created lazily at Check SSH / Run / the explicit
        #  "Open Connector Setup" button.)


        # =========================================================
        # Actions
        # =========================================================
        run_btn = W.Button(description="Submit job", button_style="success", icon="play")
        clear_btn = W.Button(description="Clear", icon="trash")
        status_chip = W.HTML(status_html("idle"))

        def should_use_connector() -> bool:
            return current_remote_bridge().uses_connector()

        def _prepare_effective_example(*, test_mode: bool, for_cloud: bool = False):
            """Validate the local example path and stage a user-owned working
            copy when the run needs one: Basic-mode ISSM md overrides
            (validated + injected before the first solve), Basic-mode Icepack
            overrides, and/or referenced datasets to materialise. The
            canonical example is never modified.

            Shared by every execution path -- Local/Remote via ``on_run``,
            Cloud via ``_launch_cloud_run`` -- one staging implementation,
            never duplicated. Returns ``(effective_example_dir,
            md_run_provenance)`` on success; on failure it has already
            reported the error (status chip + Run Log) and returns ``None``.

            ``for_cloud`` (accurate for both callers -- ``_launch_cloud_run``
            passes ``True`` unconditionally; ``on_run`` passes whether
            ``mode_dd.value == "cloud"``, already resolved before this call)
            additionally stages Icepack's cloud output collector alongside
            run.py when THIS call is the one that stages a working copy --
            Local/Remote staging is completely unaffected.
            """
            if not example_dir.value.strip():
                status_chip.value = status_html("fail")
                with log_out:
                    print("[remote][ERROR] Example path is empty.")
                return None

            local_example = Path(example_dir.value).expanduser()
            if not local_example.exists():
                status_chip.value = status_html("fail")
                with log_out:
                    print(f"[remote][ERROR] Example path does not exist locally: {local_example}")
                return None

            effective_example_dir = example_dir.value
            md_run_provenance: dict = {}
            if model_dd.value == "issm" and not test_mode:
                _md_validation = md_panel.validate()
                if not _md_validation.ok:
                    status_chip.value = status_html("fail")
                    with log_out:
                        print("[md][ERROR] ISSM configuration is not valid:")
                        for _err in _md_validation.errors:
                            print("  -", _err)
                    return None
                _has_ds_refs = bool(
                    workspace_manager.example_dataset_references(example_dir.value)
                )
                if _md_validation.normalized or _has_ds_refs:
                    _extra = (
                        {"cryostack_md_overrides.m":
                         build_md_override_script(_md_validation.normalized)}
                        if _md_validation.normalized else None
                    )
                    try:
                        _staged = workspace_manager.stage_example_for_run(
                            source_example=example_dir.value,
                            extra_files=_extra,
                            entrypoint_transform=(
                                inject_override_step if _md_validation.normalized else None
                            ),
                            overrides=_md_validation.normalized or None,
                        )
                    except Exception as _stage_err:
                        status_chip.value = status_html("fail")
                        with log_out:
                            print("[stage][ERROR] Could not stage a working copy:",
                                  type(_stage_err).__name__, _stage_err)
                        return None
                    effective_example_dir = str(_staged.path)
                    md_run_provenance = {
                        "md_overrides": _md_validation.normalized,
                        "md_working_copy": str(_staged.path),
                        "md_example_source": _staged.source,
                        "md_working_copy_from_canonical": _staged.from_canonical,
                        "staged_datasets": _staged.provenance.get("staged_datasets", []),
                    }
                    with log_out:
                        print(f"[stage] working copy: {_staged.path}")
                        if _md_validation.normalized:
                            print("[stage] md overrides: "
                                  f"{', '.join(sorted(_md_validation.normalized))}")
                        for _d in _staged.provenance.get("staged_datasets", []):
                            print(f"[stage] dataset -> {_d['as']}")

            elif model_dd.value == "icepack" and not test_mode:
                # Basic-mode Icepack overrides: an exact, single-line, validated
                # substitution in a user-owned working copy of the notebook/
                # script. Fail-closed if the example does not expose a param.
                _ip_validation = icepack_basic_panel.validate()
                if not _ip_validation.ok:
                    status_chip.value = status_html("fail")
                    with log_out:
                        print("[icepack][ERROR] Basic configuration is not valid:")
                        for _err in _ip_validation.errors:
                            print("  -", _err)
                    return None
                _ip_ds_refs = bool(
                    workspace_manager.example_dataset_references(example_dir.value)
                )
                if _ip_validation.normalized or _ip_ds_refs:
                    _ip_entry = (run_target.value or "").strip()
                    try:
                        _staged = workspace_manager.stage_example_for_run(
                            source_example=example_dir.value,
                            entrypoint=_ip_entry or "runme.m",
                            entrypoint_transform=(
                                entrypoint_transform_for(_ip_validation.normalized)
                                if _ip_validation.normalized else None
                            ),
                            overrides=_ip_validation.normalized or None,
                            # cloud only: stage the output collector as an
                            # ordinary file alongside run.py -- never
                            # embedded into the Batch runner script itself.
                            extra_files=(
                                _icepack_cloud_postprocess_files()
                                if for_cloud else None
                            ),
                        )
                    except (IcepackOverrideError, IcepackParameterError) as _ov_err:
                        status_chip.value = status_html("fail")
                        with log_out:
                            print("[icepack][ERROR]", _ov_err)
                        return None
                    except Exception as _stage_err:
                        status_chip.value = status_html("fail")
                        with log_out:
                            print("[stage][ERROR] Could not stage a working copy:",
                                  type(_stage_err).__name__, _stage_err)
                        return None
                    effective_example_dir = str(_staged.path)
                    md_run_provenance = {
                        "parameter_overrides": _ip_validation.normalized,
                        "working_copy": str(_staged.path),
                        "example_source": _staged.source,
                        "working_copy_from_canonical": _staged.from_canonical,
                        "staged_datasets": _staged.provenance.get("staged_datasets", []),
                    }
                    with log_out:
                        print(f"[stage] working copy: {_staged.path}")
                        if _ip_validation.normalized:
                            print("[stage] icepack overrides: "
                                  f"{', '.join(sorted(_ip_validation.normalized))}")

            return effective_example_dir, md_run_provenance

        def _launch_cloud_run(review) -> None:
            """The Launch cloud run entry point (Review & Launch).

            Execution goes EXCLUSIVELY through the cloud/AWS controller --
            this function never reads ``mode_dd``, never touches
            ``cluster_host``/``cluster_user``, never calls
            ``enforce_remote_access`` or the Slurm validator. The Remote/HPC
            Host/User validation inside ``on_run`` is structurally
            unreachable from here: this callback does not call ``on_run``.
            """
            log_out.clear_output()
            status_chip.value = status_html("running")
            _prepared = _prepare_effective_example(test_mode=False, for_cloud=True)
            if _prepared is None:
                return
            effective_example_dir, md_run_provenance = _prepared
            _submit_cloud_run(effective_example_dir, md_run_provenance, review=review)

        def on_run(_=None):
            log_out.clear_output()
            status_chip.value = status_html("running")

            action = advanced_action_dd.value
            mode = mode_dd.value

            # ----------------------------------------
            # DEPLOY  (clone the selected example into the user's workspace)
            # ----------------------------------------
            if ui_mode_dd.value == "advanced" and action == "deploy":
                editor_panel.controller.clone_example()
                status_chip.value = status_html("done")
                return

            # ----------------------------------------
            # TEST (force environment check)
            # ----------------------------------------
            test_mode = (
                ui_mode_dd.value == "advanced"
                and action == "test"
            )

            if mode == "remote" and access_mode_dd.value == "connector":
                create_or_refresh_connector_session()

                st = relay_check_status(SESSION["id"], force=True)
                if not st.get("online"):
                    status_chip.value = status_html("fail")
                    with log_out:
                        print("[connector][ERROR] Connector session is not online.")
                        print("[connector] Start the local connector with the session WebSocket URL, then retry.")
                    return

            # Remote/HPC host+identity validation is REMOTE-ONLY. It must
            # never fire for Cloud (or any future non-remote mode): a
            # cloud-reviewed run never configures cluster_host/cluster_user,
            # and reaching this block for a cloud run previously produced
            # "[remote][ERROR] Host and User are required." even though the
            # user never touched the Remote HPC connection fields.
            if mode == "remote":
                host = cluster_host.value.strip()
                user = cluster_user.value.strip()
                port = int(cluster_port.value)

                if not host or not user:
                    status_chip.value = status_html("fail")
                    with log_out:
                        print("[remote][ERROR] Host and User are required.")
                    return

            # B3: remote-access identity gate. Verifies the real remote identity
            # (fresh whoami) against the configured HPC username and blocks Run
            # on mismatch / unverified access / missing prerequisites.
            if mode == "remote":
                _resolved = "connector" if should_use_connector() else "direct"
                _gate = enforce_remote_access(
                    current_remote_bridge(mode=_resolved),
                    profile=get_compute_profile(cluster_name_for_keys.value or "pace"),
                    access_mode=access_mode_dd.value,
                    resolved_mode=_resolved,
                    hpc_username=user,
                    remote_directory=remote_base_dir.value.strip(),
                    connector_online=(
                        relay_check_status(SESSION["id"]).get("online")
                        if _resolved == "connector" and SESSION.get("id") else None
                    ),
                )
                for _w in _gate.warnings:
                    with log_out:
                        print(_w)
                try:
                    remote_conn_panel.set_status_from_access(_gate.state)
                except NameError:
                    pass
                if not _gate.ok:
                    status_chip.value = status_html("fail")
                    with log_out:
                        for _m in _gate.messages:
                            print(_m)
                    return

                # B4: pre-submit Slurm resource validation (internal consistency
                # + syntax only; no invented site limits).
                _slurm_errors = validate_slurm_resources(
                    nodes=slurm_nodes.value,
                    tasks=slurm_ntasks.value,
                    tasks_per_node=slurm_tpn.value,
                    wall_time=slurm_time.value,
                    memory=slurm_mem.value,
                    account=slurm_account.value,
                    account_required=get_compute_profile(
                        cluster_name_for_keys.value or "pace"
                    ).account_required,
                )
                if _slurm_errors:
                    status_chip.value = status_html("fail")
                    with log_out:
                        print("[slurm][ERROR] Fix the job resource request:")
                        for _m in _slurm_errors:
                            print("  -", _m)
                    return

            _prepared = _prepare_effective_example(
                test_mode=test_mode, for_cloud=(mode == "cloud"))
            if _prepared is None:
                return
            effective_example_dir, md_run_provenance = _prepared

            # =========================================================
            # CLOUD  (AWS Batch)  -- C4/C5
            # validate config + preflight -> stage a working copy to S3 ->
            # submit-job -> register a real cloud run in the Workspace.
            # =========================================================
            if mode == "cloud":
                _submit_cloud_run(
                    effective_example_dir, md_run_provenance,
                    review=_cloud.pop("pending_review", None),
                )
                return

            # ICESEE-Spack scientific runs are blocked unless the live
            # environment probe reports Ready. Never install silently at Run.
            if mode != "cloud" and backend_dd.value == "spack":
                try:
                    _env = current_remote_bridge(
                        mode="connector" if should_use_connector() else "direct"
                    ).environment_status(
                        model=model_dd.value,
                        remote_base=remote_base_dir.value.strip(),
                        spack_dirname=spack_dirname.value.strip() or "ICESEE-Spack",
                    )
                except Exception as _env_err:
                    status_chip.value = status_html("fail")
                    with log_out:
                        print("[spack][ERROR] Could not check the environment:",
                              type(_env_err).__name__, _env_err)
                    return
                if not _env.is_ready:
                    status_chip.value = status_html("fail")
                    spack_env_badge.value = status_badge_html(
                        _env.status.badge_state, label=_env.status.label
                    )
                    with log_out:
                        print(
                            f"ICESEE-Spack is not ready for {model_dd.value.upper()} "
                            "on this resource."
                        )
                        print("Check or prepare the environment before running.")
                        for _m in _env.messages:
                            print(" ", _m)
                    return

            try:
                # Resolve the reproducibility provenance BEFORE any job is
                # submitted or any manifest is written, so a resolution failure
                # cannot leave a half-registered run. Tested = image stack, no
                # network. Custom = resolve each requested ref to an exact SHA
                # now; the job only ever receives resolved SHAs.
                stack_provenance = {}
                stack_line = ""
                if backend_dd.value == "container":
                    _profile = software_panel.profile()
                    _selections = software_panel.selections()
                    if _is_oci_source():
                        _img_err = image_panel.validate()
                        if _img_err:
                            status_chip.value = status_html("fail")
                            with log_out:
                                print("[container][ERROR]", _img_err)
                            return
                    try:
                        stack_provenance = resolve_stack(
                            model=model_dd.value,
                            profile=_profile,
                            selections=_selections,
                            container_source=container_source.value,
                            image_uri=effective_image_uri(),
                            tested_image_key=selected_tested_image_key(),
                            digest_resolver=None,
                        )
                    except (StackCompatError, ComponentResolutionError,
                            StackRuntimeError, ContainerIdentityError) as stack_err:
                        status_chip.value = status_html("fail")
                        with log_out:
                            print("[stack][ERROR]", stack_err)
                        return
                    stack_line = stack_log_line(stack_provenance)
                    with log_out:
                        print(stack_line)

                # Site-specific runtime config (e.g. MATLAB licensing) comes from
                # the compute-resource profile, never the container image.
                _compute_profile = get_compute_profile(cluster_name_for_keys.value or "pace")
                _matlab_license = _compute_profile.matlab_license_config()

                # ISSM runs MATLAB inside the container; fail now (not after a
                # multi-hour allocation blocks on license checkout) if the
                # compute resource has no MATLAB license configured.
                if (
                    backend_dd.value == "container"
                    and model_dd.value == "issm"
                    and _matlab_license is None
                ):
                    status_chip.value = status_html("fail")
                    with log_out:
                        print(
                            "[container][ERROR] MATLAB licensing is not configured "
                            "for this compute resource."
                        )
                    return

                use_connector = should_use_connector()
                if use_connector:
                    execution_result = current_remote_bridge(mode="connector").submit(
                        direct_kwargs={},
                        connector_kwargs=dict(
                        session_id=SESSION["id"],
                        host=host,
                        user=user,
                        port=port,
                        remote_base_dir=remote_base_dir.value,
                        remote_tag=remote_tag.value,
                        backend=backend_dd.value,
                        model=model_dd.value,
                        example_dir=effective_example_dir,
                        exec_dir=exec_dir.value,
                        image_uri=effective_image_uri(),
                        container_source=container_source.value,
                        spack_enable=spack_enable.value,
                        spack_repo_url=spack_repo_url.value,
                        spack_dirname=spack_dirname.value,
                        spack_install_if_needed=spack_install_if_needed.value,
                        spack_install_mode=spack_install_mode.value,
                        spack_slurm_dir=spack_slurm_dir.value,
                        spack_pmix_dir=spack_pmix_dir.value,
                        slurm_time=slurm_time.value,
                        slurm_job_name=slurm_job_name.value,
                        slurm_nodes=slurm_nodes.value,
                        slurm_ntasks=slurm_ntasks.value,
                        slurm_tpn=slurm_tpn.value,
                        slurm_part=slurm_part.value,
                        slurm_mem=slurm_mem.value,
                        slurm_account=slurm_account.value,
                        slurm_mail=slurm_mail.value,
                        test_mode=test_mode,
                        run_file=selected_run_file(),
                        cluster_name=cluster_name_for_keys.value or "pace",
                        stack_log_line=stack_line,
                        stack_software=stack_provenance.get("software") or {},
                        matlab_license=_matlab_license,
                        ),
                    )
                else:
                    execution_result = current_remote_bridge(mode="direct").submit(
                        connector_kwargs={},
                        direct_kwargs=dict(
                        host=host,
                        user=user,
                        port=port,
                        remote_base_dir=remote_base_dir.value,
                        remote_tag=remote_tag.value,
                        backend=backend_dd.value,
                        model=model_dd.value,
                        example_dir=effective_example_dir,
                        exec_dir=exec_dir.value,
                        image_uri=effective_image_uri(),
                        container_source=container_source.value,
                        spack_enable=True,
                        spack_repo_url="https://github.com/ICESEE-project/ICESEE-Spack.git",
                        spack_dirname="ICESEE-Spack",
                        spack_install_if_needed=False,
                        spack_install_mode="--with-issm" if model_dd.value == "issm" else "--with-icepack",
                        spack_slurm_dir="",
                        spack_pmix_dir="",
                        slurm_time=slurm_time.value,
                        slurm_job_name=slurm_job_name.value,
                        slurm_nodes=slurm_nodes.value,
                        slurm_ntasks=slurm_ntasks.value,
                        slurm_tpn=slurm_tpn.value,
                        slurm_part=slurm_part.value,
                        slurm_mem=slurm_mem.value,
                        slurm_account=slurm_account.value,
                        slurm_mail=slurm_mail.value,
                        test_mode=test_mode,
                        run_file=selected_run_file(),
                        stack_log_line=stack_line,
                        stack_software=stack_provenance.get("software") or {},
                        matlab_license=_matlab_license,
                        ),
                    )

                result = {
                    "remote_dir": execution_result.working_directory,
                    "jobid": execution_result.job_id,
                    "log_file": execution_result.log_path,
                    "messages": execution_result.messages,
                }

                STATUS["remote_dir"] = result["remote_dir"]
                STATUS["jobid"] = result["jobid"]
                STATUS["log_file"] = result.get("log_file")

                workspace_bridge.start_run(
                    name=Path(STATUS["remote_dir"]).name,
                    model=model_dd.value,
                    backend=backend_dd.value,
                    execution_mode=mode_dd.value,
                    jobid=STATUS["jobid"],
                    remote_directory=Path(STATUS["remote_dir"]),
                    log_file=(
                        Path(STATUS["log_file"])
                        if STATUS.get("log_file")
                        else None
                    ),
                    metadata={
                        "host": cluster_host.value.strip(),
                        "user": cluster_user.value.strip(),
                        "port": int(cluster_port.value),
                        "access_mode": access_mode_dd.value,
                        "cluster_name": cluster_name_for_keys.value or "pace",
                        **md_run_provenance,
                    },
                    container=stack_provenance.get("container") or {},
                    software=stack_provenance.get("software") or {},
                )

                experiment_bridge.create(
                    application="cryolauncher",

                    name=(
                        f"{model_dd.value.upper()} "
                        f"{backend_dd.value} run"
                    ),

                    backend=backend_dd.value,

                    status="running",

                    job_id=str(result["jobid"]),

                    cluster=(
                        cluster_name_for_keys.value
                        or cluster_host.value.strip()
                    ),

                    working_directory=(
                        result["remote_dir"]
                    ),

                    output_directory=(
                        f"{result['remote_dir']}/outputs"
                    ),

                    log_path=result.get("log_file"),

                    configuration=(
                        current_experiment_configuration()
                    ),

                    metadata={
                        "execution_mode": mode_dd.value,
                        "access_mode": access_mode_dd.value,
                        "model": model_dd.value,
                    },
                )

                workspace_bridge.save(
                    application="cryolauncher",
                    state=current_workspace_state(),
                )

                with log_out:
                    for msg in result["messages"]:
                        print(msg)

                status_chip.value = status_html("done")

            except subprocess.TimeoutExpired:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[remote][TIMEOUT] Submission timed out.")
            except Exception as e:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def on_clear(_=None):
            log_out.clear_output()
            results_out.clear_output()
            status_chip.value = status_html("idle")

        remote_runtime = build_remote_runtime_callbacks(
            runtime_status=STATUS,
            log_output=log_out,
            status_widget=status_chip,
            status_html=status_html,
            bridge_factory=current_remote_bridge,
            experiment_bridge=experiment_bridge,
            experiment_update_from_job_status=experiment_update_from_job_status,
            on_status_result=workspace_manager.update_run_status_by_job,
        )
        _remote_check = remote_runtime.check

        def on_test_remote(_=None):
            # Immediate feedback before any blocking SSH/relay work: disable the
            # button and show "Checking…" so a repeat click can't re-enter and
            # the user sees the check is running.
            connect_btn.disabled = True
            try:
                remote_conn_panel.set_status("checking")
            except NameError:
                pass
            try:
                _on_test_remote_impl(_)
            finally:
                connect_btn.disabled = False

        def _on_test_remote_impl(_=None):
            _check_result = _remote_check(_)
            if mode_dd.value != "remote":
                return
            _profile = get_compute_profile(cluster_name_for_keys.value or "pace")

            # Connectivity failed: classify it. A public-key rejection is an
            # actionable "your CryoStack key is not registered yet" state (B3
            # moved to a per-user/resource namespaced key); everything else is
            # a generic failure. Never run identity verification on a failed
            # connection.
            if not _check_result or not _check_result.get("ok"):
                _kind = classify_ssh_failure(
                    stderr=(_check_result or {}).get("stderr", ""),
                    stdout=(_check_result or {}).get("stdout", ""),
                    returncode=(_check_result or {}).get("returncode"),
                )
                try:
                    if _kind == SSH_KEY_NOT_AUTHORIZED:
                        remote_conn_panel.set_key_unregistered(_profile)
                        with log_out:
                            print("[access] SSH key not registered — the Connector "
                                  "reached the resource, but this CryoStack key is "
                                  "not yet authorized for your account. See the "
                                  "Remote connection panel for how to register it.")
                    else:
                        remote_conn_panel.set_status("failed")
                except NameError:
                    pass
                return
            try:
                _resolved = "connector" if should_use_connector() else "direct"
                _vcmd = _profile.verification_command
                # The connectivity probe above already ran `hostname && whoami
                # && pwd` in one command. When the resource's identity check is
                # just `whoami`, reuse that output instead of a second remote
                # round trip. (The Run gate still re-verifies fresh.)
                _reuse_line = ""
                if (
                    _check_result
                    and _check_result.get("ok")
                    and can_reuse_connectivity_identity(_vcmd)
                ):
                    _lines = [
                        ln.strip()
                        for ln in (_check_result.get("stdout") or "").splitlines()
                        if ln.strip()
                    ]
                    if len(_lines) >= 2:
                        _reuse_line = _lines[1]   # hostname, whoami, pwd
                if _reuse_line:
                    _v = identity_result_from_output(
                        whoami_line=_reuse_line,
                        expected_username=cluster_user.value.strip(),
                    )
                else:
                    _v = verify_remote_identity(
                        current_remote_bridge(mode=_resolved),
                        verification_command=_vcmd,
                        expected_username=cluster_user.value.strip(),
                    )
                with log_out:
                    if _v.ok:
                        print(f"[identity] verified — remote whoami '{_v.remote_identity}' "
                              "matches the configured HPC username.")
                    elif _v.mismatch:
                        print(f"[identity][MISMATCH] remote whoami '{_v.remote_identity}' "
                              f"!= configured HPC username '{_v.expected}'. Run is blocked "
                              "until this matches.")
                    else:
                        print(f"[identity] could not verify remote identity: {_v.error}")
                try:
                    if _v.ok:
                        remote_conn_panel.set_status("verified")
                    elif _v.mismatch:
                        remote_conn_panel.set_status("mismatch")
                    else:
                        remote_conn_panel.set_status("failed")
                except NameError:
                    pass
            except Exception as _e:
                with log_out:
                    print("[identity] verification skipped:", type(_e).__name__, _e)
                try:
                    remote_conn_panel.set_status("failed")
                except NameError:
                    pass

        on_status = remote_runtime.status
        on_terminate = remote_runtime.terminate

        workspace_logs = build_workspace_logs(
            status=STATUS,
            session=SESSION,
            auto_tail=AUTO_TAIL,
            log_output=log_out,
            status_widget=status_chip,
            auto_tail_button=auto_tail_btn,
            cluster_host=cluster_host,
            cluster_user=cluster_user,
            cluster_port=cluster_port,
            access_mode=access_mode_dd,
            normalize_remote_path=normalize_remote_path,
            status_html=status_html,
            send_command=send_command,
            ssh_run=ssh_run,
            bridge_factory=current_remote_bridge,
        )
        on_tail = workspace_logs.on_tail
        on_auto_tail_change = workspace_logs.on_auto_tail_change

        def _cloud_status_result(job_id, state):
            workspace_manager.update_run_status_by_job(job_id, state)
            _set_cloud_state(state if state in _CLOUD_STATES else "checking")

        # smoke test: a local config check (precheck) then the AWS probe (worker).
        # Both share the resolved config; the worker never touches a widget.
        _smoke_state: dict = {}

        def _smoke_precheck():
            from cryostack_src.cloud.drivers.aws.batch_config import (
                ECR_REPOSITORY_NAMES,
            )
            _model = model_dd.value
            _cfg = resolve_cloud_config(
                provider="aws", region=aws_region.value.strip(),
                bucket=cloud_bucket.value.strip(), profile=aws_profile.value.strip(),
                model=_model, job_queue=batch_job_queue.value.strip(),
                job_definition=batch_job_def.value.strip(),
            )
            problems = validate_cloud_config(_cfg, model=_model)
            _smoke_state.update(
                cfg=_cfg, ecr=ECR_REPOSITORY_NAMES.get(_model, ""),
                user_prefix=workspace_manager.owner.safe_id)
            return problems

        def _smoke_worker():
            from cryostack_src.cloud import run_infrastructure_smoke_test
            _cfg = _smoke_state["cfg"]
            # a connected BYO account probes ITS own infrastructure with a
            # fresh assumed-role session; developer mode keeps the profile.
            _ex = _resolve_cloud_execution()
            _byo = getattr(_ex, "credentials", None) if getattr(_ex, "is_byo", False) else None
            return run_infrastructure_smoke_test(
                region=(_ex.region if _byo else _cfg.region), bucket=_cfg.bucket,
                user_prefix=_smoke_state["user_prefix"],
                job_queue=_cfg.job_queue, job_definition=_cfg.job_definition,
                ecr_repository=_smoke_state["ecr"],
                profile=None if _byo else _cfg.profile,
                credentials=_byo,
            )

        # forward-declared: the review callbacks are built after cloud_runtime,
        # but _update_environment (Test / Prepare success) must refresh the
        # compact RUN ESTIMATE line once infrastructure is Ready.
        _review_holder = {"refresh": lambda: None}
        # forward-declared: the active-run card is wired after the Workspace
        # tabs exist (it navigates to Run Log / Results); the CloudRunController
        # only needs the render hook now.
        _active_run_holder = {"render": lambda **_v: None}

        cloud_runtime = build_cloud_runtime_callbacks(
            runtime_status=STATUS,
            log_output=log_out,
            status_widget=status_chip,
            status_html=status_html,
            bridge_factory=current_cloud_bridge,
            cloud_environment=cloud_environment,
            set_cloud_status=set_cloud_status,
            bucket_value=lambda: cloud_bucket.value.strip(),
            results_output=results_out,
            execution_resolver=_resolve_cloud_execution,
            on_status_result=_cloud_status_result,
            smoke_button=cloud_smoke_btn,
            set_chip=_set_cloud_state,
            smoke_precheck=_smoke_precheck,
            smoke_worker=_smoke_worker,
            on_environment_update=lambda _caps: _review_holder["refresh"](),
        )
        on_cloud_status = cloud_runtime.status
        on_cloud_logs = cloud_runtime.logs
        on_cloud_terminate = cloud_runtime.terminate
        on_cloud_results = cloud_runtime.results

        # -- "Connect AWS Account" onboarding (C7.2) --------------------
        # Bring-your-own-AWS-account: the connection is owned by the
        # authenticated CryoStack user; a fresh AWSOnboarding per call keeps
        # nothing user-controlled in the identity path.
        def _aws_onboarding_factory():
            from cryostack_src.cloud.connect import AWSOnboarding

            return AWSOnboarding(
                user=workspace_manager.owner,
                region=(cloud_environment.region.value or "us-east-2").strip(),
            )

        def _on_aws_account_state(summary: dict) -> None:
            """Once the account is verified, Prepare cloud -- not Test
            connection -- is the normal-user action. Re-check lives in the AWS
            ACCOUNT block.

            Also keeps the Cloud state chip honest: a deployment that IS
            configured but whose user connection needs attention must never
            read "Not configured" (that label is reserved for genuinely
            nothing attempted yet)."""
            status = (summary or {}).get("status")
            connected = status == "connected"
            cloud_environment.test_button.layout.display = (
                "none" if connected else "inline-flex"
            )
            if status == "connected":
                _set_cloud_state("connected")
            elif status == "error":
                _set_cloud_state("connection_issue")
            elif status == "pending":
                _set_cloud_state("connection_required")
            elif status == "disconnected":
                _set_cloud_state("not_configured")

        aws_connect = build_aws_connect_callbacks(
            widgets=cloud_environment,
            onboarding_factory=_aws_onboarding_factory,
            log_output=log_out,
            on_state=_on_aws_account_state,
        )
        cloud_environment.connect_button.on_click(aws_connect.connect)
        cloud_environment.verify_button.on_click(aws_connect.verify)
        cloud_environment.recheck_button.on_click(aws_connect.recheck)
        cloud_environment.disconnect_button.on_click(aws_connect.disconnect)
        # failed-verification recovery: repair the same account, or start a
        # STAGED switch to a different one (C7 live-acceptance fix -- an
        # "error" connection used to have no reachable action). Change AWS
        # account never touches the active connection until the replacement
        # itself verifies -- see cloud_connect_runtime.build_aws_connect_callbacks.
        cloud_environment.retry_button.on_click(aws_connect.retry)
        cloud_environment.change_account_button.on_click(aws_connect.change_account)
        cloud_environment.change_verify_button.on_click(aws_connect.change_verify)
        cloud_environment.change_cancel_button.on_click(aws_connect.change_cancel)
        try:
            aws_connect.refresh()          # render any existing connection
        except Exception as _err:          # noqa: BLE001 - never block panel build
            with log_out:
                print("[cloud][connect] state unavailable:", _err)

        # -- C6: non-blocking submit + auto-poll + auto-retrieve -----------
        from cryostack_src.frontend.cryolauncher.cloud_runtime import _emit_log

        def _cloud_log(message: str) -> None:
            # CloudRunController drives this from a detached asyncio task, where
            # `with log_out: print(...)` silently drops output (no kernel
            # parent-header). append_stdout writes straight to the synced
            # outputs traitlet, so the Run Log actually shows the run.
            _emit_log(log_out, message)

        def _cloud_results_ready() -> None:
            # outputs are already in this user's local run cache (cloud_outputs);
            # re-read the shared ResultPackage for the selected run and render an
            # initial plot -- the same panel every backend uses, no cloud path.
            try:
                workspace_history_panel.refresh_button.click()
            except Exception:
                pass
            try:
                visualization_panel.controller.preview()
            except Exception:
                try:
                    visualization_panel.controller.refresh()
                except Exception:
                    pass
            with results_out:
                print("[cloud] Outputs retrieved into your run cache and "
                      "rendered in Results. Use Download Results / Download "
                      "Figures to export.")

        def _persist_cloud_resources(job_id, resources):
            """Non-blocking, no-AWS: fold the controller's grown resource
            snapshot into the run manifest so the AWS diagnostics menu
            survives a page refresh and a historical run keeps its OWN
            resources. Only non-secret identity (the controller already
            enforces this via merge_aws_resources)."""
            try:
                workspace_manager.merge_run_metadata_by_job(
                    str(job_id), {"aws_resources": dict(resources or {})})
            except Exception as _pe:  # noqa: BLE001 - never break a poll
                with log_out:
                    print("[cloud][diagnostics] (non-fatal)", type(_pe).__name__, _pe)

        _cloud["controller"] = CloudRunController(
            bridge_factory=current_cloud_bridge,
            register_run=_register_cloud_run,
            sync_results=workspace_manager.sync_cloud_results,
            on_state=_set_cloud_state,
            on_log=_cloud_log,
            on_results_ready=_cloud_results_ready,
            # every AWS op of a connected BYO run uses a fresh sts:AssumeRole
            # for the reviewed account -- no ambient/profile fallback.
            execution_provider=_resolve_cloud_execution,
            on_run_view=lambda **v: _active_run_holder["render"](**v),
            on_resources=_persist_cloud_resources,
            poll_interval=float(os.environ.get("CRYOSTACK_CLOUD_POLL_SECONDS", "20")),
        )

        # The infrastructure smoke test (license-neutral: identity + S3 + Batch
        # + ECR reachability, no job submitted) shares the same non-blocking
        # coordinator as Test connection / Prepare cloud.
        cloud_smoke_btn.on_click(cloud_runtime.smoke_test)

        # -- RUN ESTIMATE + Review & Launch (C7.4) --------------------------
        from cryostack_src.cloud.estimate import (
            estimate_cloud_cost,
            estimate_runtime,
            resolve_fargate_prices,
        )
        from cryostack_src.cloud.review import (
            InfrastructureReadiness,
            build_cloud_run_review,
            review_digest,
        )
        from cryostack_src.frontend.cryolauncher.cloud_review_runtime import (
            build_cloud_review_callbacks,
        )

        def _cloud_example_name() -> str:
            return Path(example_dir.value or "").name or "example"

        def _cloud_run_config():
            """THE canonical resolved cloud config -- resources included,
            derived from whichever model is currently selected. The Review
            card and the submit path both read this; no second copy."""
            _model = (model_dd.value or "issm").strip().lower()
            _job_def, _ = resolve_job_definition(
                _model, batch_job_def.value.strip(), allow_list=_CLOUD_JOB_DEFS,
            )
            return resolve_cloud_config(
                provider="aws",
                region=aws_region.value.strip(),
                bucket=cloud_bucket.value.strip(),
                profile=aws_profile.value.strip(),
                model=_model,
                job_queue=batch_job_queue.value.strip(),
                job_definition=_job_def,
            )

        def _cloud_run_history():
            """Durations (minutes) of this user's past successful cloud runs of
            the CURRENTLY SELECTED model + example -- best effort; empty ->
            the estimator falls back."""
            _model = (model_dd.value or "issm").strip().lower()
            out = []
            try:
                for run in workspace_manager.list_runs():
                    if run.execution_mode != "cloud" or (run.model or "").lower() != _model:
                        continue
                    if str(run.status).lower() not in ("completed", "succeeded"):
                        continue
                    if run.finished is None or run.created is None:
                        continue
                    name = (run.name or "") + " " + str(run.metadata.get("example", ""))
                    if _cloud_example_name().lower() not in name.lower():
                        continue
                    mins = (run.finished - run.created).total_seconds() / 60.0
                    if 0 < mins < 24 * 60:
                        out.append(mins)
            except Exception:  # noqa: BLE001
                pass
            return out

        def _cloud_review_digest() -> str:
            _m = (model_dd.value or "issm").strip().lower()
            _img = _default_tested_image(_m)
            return review_digest(
                config=_cloud_run_config(),
                model=_m,
                example=_cloud_example_name(),
                run_target=(Path(run_target.value or "runme.m").name),
                account_id=_cloud_account_id_for_review(),
                scientific_overrides=(md_panel.overrides() if model_dd.value == "issm" else {}),
                image_digest=getattr(_img, "digest", "") or "",
            )

        def _cloud_account_id_for_review() -> str:
            try:
                s = _aws_onboarding_factory().summary()
                return s.get("account_id", "") if s.get("status") == "connected" else ""
            except Exception:  # noqa: BLE001
                return ""

        def _build_cloud_review():
            _model = (model_dd.value or "issm").strip().lower()
            cfg = _cloud_run_config()
            region = cfg.region
            account_id = _cloud_account_id_for_review()

            # fresh account verification (BYO) -- never uses stored STS creds
            account_fresh = False
            creds = None
            try:
                _ex = _resolve_cloud_execution()
                account_fresh = _ex.is_byo
                creds = _ex.credentials
                if _ex.is_byo:
                    region = _ex.region
                    account_id = _ex.account_id or account_id
                    cfg = _cloud_run_config()
                    cfg.region = region
                    if _ex.defaults:
                        cfg.bucket = _ex.defaults.bucket
            except Exception as _acc_err:  # noqa: BLE001 - fail closed, not crash
                account_fresh = False

            # readiness
            try:
                caps = current_cloud_bridge(
                    credentials=creds, region=region
                ).check_environment()
            except Exception:  # noqa: BLE001
                caps = None
            infra = InfrastructureReadiness(
                account=bool(getattr(caps, "authenticated", False)) and account_fresh,
                storage=bool(getattr(caps, "storage_ready", False)),
                container=bool(getattr(caps, "registry_ready", False)),
                compute=bool(getattr(caps, "batch_ready", False)),
            )

            rt = estimate_runtime(
                model=_model, example=_cloud_example_name(),
                time_limit_minutes=cfg.time_limit_minutes,
                history_provider=_cloud_run_history,
            )
            prices = resolve_fargate_prices(region)          # ambient; account-neutral
            cost = estimate_cloud_cost(
                region=region, vcpu=cfg.vcpu, memory_gib=cfg.memory_gib,
                expected_runtime_minutes=rt.minutes, ephemeral_gib=cfg.ephemeral_gib,
                prices=prices, runtime_source=rt.source,
            )
            # the MATLAB-license gate is ISSM-only (cloud_run_preflight skips
            # it for every other model) -- unchanged behaviour, just no
            # longer computed against a hardcoded "issm".
            _lic = _cloud_matlab_license_configured()
            return build_cloud_run_review(
                config=cfg, model=_model, example=_cloud_example_name(),
                run_target=(Path(run_target.value or "runme.m").name),
                account_id=account_id, region=region,
                infrastructure=infra, runtime=rt, cost=cost,
                account_freshly_verified=account_fresh,
                config_problems=validate_cloud_config(cfg, model=_model),
                preflight_problems=cloud_run_preflight(
                    model=_model, matlab_license_configured=_lic),
                scientific_overrides=(md_panel.overrides() if model_dd.value == "issm" else {}),
                issm_runtime_ready=(_lic if _model == "issm" else None),
            )

        _cloud_review = build_cloud_review_callbacks(
            widgets=cloud_environment,
            review_builder=_build_cloud_review,
            digest_builder=_cloud_review_digest,
            # Launch cloud run goes DIRECTLY to the cloud/AWS controller --
            # never through on_run()'s mode/backend dispatch, so Remote/HPC
            # Host/User validation is structurally unreachable from here,
            # regardless of what mode_dd.value happens to be.
            launch_handler=_launch_cloud_run,
            log_output=log_out,
        )
        _review_holder["refresh"] = _cloud_review.refresh_estimate
        cloud_environment.review_button.on_click(_cloud_review.review)
        cloud_environment.review_back_button.on_click(_cloud_review.back)
        cloud_environment.launch_button.on_click(_cloud_review.launch)

        def tail_selected_workspace_run():
            selected = workspace_manager.selected_run()
            if selected and selected.execution_mode == "cloud":
                return on_cloud_logs()
            return on_tail()

        workspace_manager.set_tail_handler(tail_selected_workspace_run)

        def resolve_workspace_run_status(run):
            if run.execution_mode == "cloud":
                # a BYO run (account id recorded) re-checks status through a
                # FRESH assumed-role context for that account; a developer-mode
                # run keeps its profile. current_cloud_bridge picks the path.
                if run.metadata.get("account_id"):
                    bridge = current_cloud_bridge(
                        region=run.metadata.get("region") or None)
                else:
                    bridge = CloudBridge(
                        provider="aws",
                        region=run.metadata.get("region") or "us-east-2",
                        profile=run.metadata.get("profile") or None,
                    )
            else:
                bridge = RemoteBridge(
                    mode=run.metadata.get("access_mode") or "direct",
                    host=run.metadata.get("host") or cluster_host.value.strip(),
                    user=run.metadata.get("user") or cluster_user.value.strip(),
                    port=int(run.metadata.get("port") or cluster_port.value),
                    session_id=SESSION.get("id"),
                    cluster_name=run.metadata.get("cluster_name") or "pace",
                )
            return bridge.status(job_id=str(run.jobid)).state

        workspace_manager.set_status_resolver(resolve_workspace_run_status)

        def active_execution_mode():
            selected = workspace_manager.selected_run()
            return selected.execution_mode if selected else mode_dd.value

        def _selected_cloud_run_s3():
            """The S3 run location for the selected cloud run -- from its
            persisted metadata, falling back to this session's last submit."""
            selected = workspace_manager.selected_run()
            if selected and selected.execution_mode == "cloud":
                loc = selected.metadata.get("cloud_run")
                if loc:
                    return str(loc)
            return STATUS.get("cloud_run")

        def sync_selected_run_results():
            """Synchronise the selected run's outputs into its local run cache,
            using whichever backend produced it. Returns the local outputs dir
            (or None). Performs no rendering."""
            if active_execution_mode() == "cloud":
                s3 = _selected_cloud_run_s3()
                if not s3:
                    with results_out:
                        print("[cloud] No cloud run location for the selected run.")
                    return None
                return current_cloud_bridge().results(s3_uri=s3)
            return workspace_manager.refresh_results()

        def on_results_preview(_=None):
            # 1. fetch/synchronise outputs + print the run summary, 2. drive the
            # structured visualization panel: re-read the local package, rebuild
            # Solution/Field/Timestep, and render an initial recommended plot.
            if active_execution_mode() == "cloud":
                try:
                    _p = sync_selected_run_results()
                    with results_out:
                        if _p:
                            print("[cloud] Results synchronised:", _p)
                except Exception as _e:
                    with results_out:
                        print("[cloud][ERROR]", type(_e).__name__, _e)
            else:
                workspace_manager.preview_results()
            visualization_panel.controller.preview()

        def on_results_download(_=None):
            if active_execution_mode() == "cloud":
                on_cloud_results()
            else:
                workspace_manager.download_results()

        def on_figures_download(_=None):
            if active_execution_mode() == "cloud":
                on_cloud_results()
            else:
                workspace_manager.download_figures()

        def current_workspace_state() -> dict:
            # v2 shape: RESOURCE facts are NOT persisted (they live in
            # ComputeProfile); personal settings are folded per-resource by the
            # controller; run settings go under "run"; nothing secret.
            state = resource_state.capture()
            state["run"] = {
                "model": model_dd.value,
                "backend": backend_dd.value,
                "execution_mode": mode_dd.value,
                "user_mode": ui_mode_dd.value,
                "example": example_picker.value or "",
                "example_directory": example_dir.value.strip(),
                "run_target": run_target.value or "",
                "job_name": slurm_job_name.value,
                "nodes": slurm_nodes.value,
                "tasks": slurm_ntasks.value,
                "tasks_per_node": slurm_tpn.value,
                "memory": slurm_mem.value,
                "wall_time_override": slurm_time.value,
                "partition_override": slurm_part.value,
            }
            state["job"] = {
                "job_id": STATUS.get("jobid"),
                "remote_directory": STATUS.get("remote_dir"),
                "log_file": STATUS.get("log_file"),
            }
            return strip_secrets(state)


        run_btn.on_click(on_run)
        clear_btn.on_click(on_clear)
        connect_btn.on_click(on_test_remote)
        status_btn.on_click(on_status)
        tail_btn.on_click(on_tail)
        # auto_tail_btn.on_click(on_auto_tail_click)
        terminate_btn.on_click(on_terminate)
        cloud_status_btn.on_click(on_cloud_status)
        cloud_logs_btn.on_click(on_cloud_logs)

        # Terminate is destructive -> two-step confirm. The controller's
        # terminate() also stops the auto-poll loop.
        _cloud_term_armed = {"v": False}

        def _reset_cloud_terminate():
            _cloud_term_armed["v"] = False
            cloud_terminate_btn.description = "Terminate"
            cloud_terminate_btn.button_style = "danger"

        def on_cloud_terminate_confirm(_=None):
            if not _cloud_term_armed["v"]:
                _cloud_term_armed["v"] = True
                cloud_terminate_btn.description = "Confirm terminate"
                cloud_terminate_btn.button_style = "warning"
                with log_out:
                    print("[cloud] Click again to confirm termination of the running job.")
                return
            _reset_cloud_terminate()
            job_id = STATUS.get("batch_job_id")
            if _cloud["controller"] is not None and job_id:
                _cloud["controller"].terminate(str(job_id))
            else:
                on_cloud_terminate()

        cloud_terminate_btn.on_click(on_cloud_terminate_confirm)
        cloud_environment.test_button.on_click(cloud_runtime.check_environment)
        cloud_environment.prepare_button.on_click(cloud_runtime.prepare_environment)
        results_download_btn.on_click(on_results_download)
        figures_download_btn.on_click(on_figures_download)
        preview_results_btn.on_click(on_results_preview)
        start_connector_session_btn.on_click(create_or_refresh_connector_session)
        bootstrap_btn.on_click(on_bootstrap_keys)
        check_backend_btn.on_click(on_check_backend)

        # =========================================================
        # CSS
        # =========================================================
        css = """
            <style>

            /*
            * CryoLauncher-specific styles remain here.
            * Shared cards, labels, layout, statuses, and typography
            * come from shared_app_styles.py.
            */

            </style>
            """

        # =========================================================
        # Layout
        # =========================================================
        header = W.HTML("""
        <div class="icesee-page">
          <div class="icesee-title">Ice-Sheet Modeling</div>
          <div class="icesee-subtitle">
            Launch supported ice-sheet models without the ICESEE data assimilation layer.
            Basic mode helps beginners discover native ISSM and Icepack examples automatically.
            Advanced mode keeps manual control for custom paths, editing, and expert workflows.
          </div>
        </div>
        """)

        ui_mode_row = form_row("User mode:", ui_mode_dd)
        mode_row = form_row("Exec mode:", mode_dd)
        backend_row = form_row("Backend:", backend_dd)
        model_row = form_row("Model:", model_dd)
        example_picker_row = form_row("Examples:", example_picker)
        example_info_row = form_row("Details:", example_info)
        example_row = form_row("Example path:", example_dir)
        exec_row = form_row("Exec dir:", exec_dir)
        advanced_action_row = form_row("Action:", advanced_action_dd)
        run_target_row = form_row("Run target:", run_target)
        md_config_panel = W.Accordion(children=[md_panel.container])
        md_config_panel.set_title(0, "⚙️ ISSM configuration (Basic)")
        # md_config_panel.selected_index = 0  # open by default
        icepack_config_panel = W.Accordion(children=[icepack_basic_panel.container])
        icepack_config_panel.set_title(0, "⚙️ Icepack configuration (Basic)")
        icepack_config_panel.selected_index = None
        container_source_row = form_row("Source:", container_source)
        image_uri_row = form_row("Image:", image_uri)

        # B4: the Remote connection and Slurm resources widgets are now arranged
        # by the shared panels (build_remote_connection_panel /
        # build_slurm_resources_panel). Only the "Tag" row is still laid out
        # here -- it goes into the panel's Diagnostics section.
        remote_tag_row = form_pair("Tag:", remote_tag, "90px")

        ssh_key_manager = build_ssh_key_manager(
            cluster_name_widget=cluster_name_for_keys,
            host_widget=cluster_host,
            user_widget=cluster_user,
            defer_probe=True,   # ssh-add subprocesses off the construction path
        )
        server_key_note = W.HTML("""
        <div class='icesee-subtle' style='line-height:1.5; margin-bottom:8px;'>
        This manages SSH keys on the web server/GHUB side for direct SSH.
        For Local Connector / VPN bridge mode, the connector creates the key on your workstation.
        </div>
        """)

        ssh_key_manager_box = W.Accordion(
            children=[
                W.VBox([
                    server_key_note,
                    ssh_key_manager,
                ], layout=W.Layout(gap="8px"))
            ]
        )

        ssh_key_manager_box.set_title(0, "🔐 Server-side SSH Key Manager")
        ssh_key_manager_box.selected_index = None

        # run the (subprocess-spawning) ssh-agent inspection only when the user
        # actually opens the key-manager panel
        def _probe_ssh_key_manager(change):
            if change.get("new") is not None:
                probe = getattr(ssh_key_manager, "_cryostack_probe", None)
                if probe is not None:
                    probe()
        ssh_key_manager_box.observe(_probe_ssh_key_manager, names="selected_index")

        # ssh_key_manager_box = W.Accordion(children=[ssh_key_manager])
        # # ssh_key_manager_box.set_title(0, "🔐 SSH Key Manager")
        # ssh_key_manager_box.set_title(0, "🔐 Server-side SSH Key Manager")
        # ssh_key_manager_box.selected_index = None

        ssh_key_manager_box.layout = W.Layout(
            width="100%",
            border="1px solid rgba(0,0,0,.08)",
            border_radius="12px",
            margin="8px 0 4px 0"
        )

        # [preview_results_btn, results_download_btn, figures_download_btn],
        download_buttons_row = build_workspace_toolbar(
            [preview_results_btn, results_download_btn],
            justify_content="flex-end",
            margin="10px 0 0 0",
        )

        # B4: user-workflow-oriented Remote Connection panel. Reorganises the
        # existing widgets (Compute resource / Your HPC identity / Access /
        # Status) and hides the connector/session internals behind Diagnostics.
        # Transport behaviour, the B3 AccessState machine, identity verification
        # and the Run gate are unchanged.
        connect_btn.description = "Check SSH Access"
        start_connector_session_btn.description = "Open Connector Setup"
        start_connector_session_btn.icon = "external-link"

        remote_conn_panel = build_remote_connection_panel(
            resource=cluster_name_for_keys,
            host=cluster_host,
            port=cluster_port,
            hpc_username=cluster_user,
            remote_directory=remote_base_dir,
            connection_method=access_mode_dd,
            auth_method=auth_mode,
            check_ssh_button=connect_btn,
            open_connector_button=start_connector_session_btn,
            connector_card=relay_status,
            connector_setup_link=connector_setup_link,
            profile=get_compute_profile(cluster_name_for_keys.value or "pace"),
            auth_extra_children=[cluster_password, bootstrap_btn],
            advanced_children=[remote_tag_row],
        )
        remote_conn_box = W.Accordion(children=[remote_conn_panel.container])
        remote_conn_box.set_title(0, "🔌 Remote connection")

        slurm_inner = build_slurm_resources_panel(
            job_name=slurm_job_name,
            wall_time=slurm_time,
            nodes=slurm_nodes,
            tasks=slurm_ntasks,
            tasks_per_node=slurm_tpn,
            partition=slurm_part,
            memory=slurm_mem,
            account=slurm_account,
            email=slurm_mail,
        ).container

        slurm_box = W.Accordion(children=[slurm_inner])
        slurm_box.set_title(0, "📊 Slurm resources")
        slurm_box.selected_index = None

        exec_backend_choice = W.Dropdown(
            options=[("ICESEE-Spack", "spack"), ("ICESEE-Container", "container")],
            value="spack",
            layout=W.Layout(width="320px"),
        )

        spack_enable = W.Checkbox(value=True, description="Use ICESEE-Spack on Remote")

        spack_repo_url = W.Text(
            value="https://github.com/ICESEE-project/ICESEE-Spack.git",
            layout=W.Layout(width="100%"),
        )

        spack_dirname = W.Text(value="ICESEE-Spack", layout=W.Layout(width="100%"))

        spack_install_if_needed = W.Checkbox(
            value=False,
            description="Run install.sh if not installed",
        )

        spack_install_mode = W.Dropdown(
            options=[
                ("Default", ""),
                ("With ISSM", "--with-issm"),
                ("With Icepack", "--with-icepack"),
                ("With Firedrake", "--with-firedrake"),
            ],
            value="--with-issm",
            layout=W.Layout(width="100%"),
        )

        spack_slurm_dir = W.Text(
            value="",
            placeholder="e.g. /opt/slurm/current",
            layout=W.Layout(width="100%"),
        )

        spack_pmix_dir = W.Text(
            value="",
            placeholder="e.g. /opt/pmix/5.0.1",
            layout=W.Layout(width="100%"),
        )

        # --- Remote + ICESEE-Spack: Environment lifecycle ------------------
        spack_env_badge = W.HTML(status_badge_html("idle", label="Unknown"))
        spack_env_setup_label = W.HTML("")
        spack_check_env_btn = W.Button(
            description="Check environment", icon="search", button_style="info",
        )
        spack_prepare_env_btn = W.Button(
            description="Prepare environment", icon="wrench", button_style="primary",
        )
        spack_setup_log_btn = W.Button(
            description="View setup log", icon="file-text",
            layout=W.Layout(display="none"),
        )
        spack_env_row = W.VBox(
            [
                W.HBox(
                    [W.HTML("<div class='icesee-lbl'>Environment</div>",
                            layout=W.Layout(width="120px", min_width="120px")),
                     spack_env_badge, spack_env_setup_label],
                    layout=W.Layout(align_items="center", gap="10px"),
                ),
                W.HBox(
                    [spack_check_env_btn, spack_prepare_env_btn, spack_setup_log_btn],
                    layout=W.Layout(gap="8px", flex_wrap="wrap", margin="0 0 0 120px"),
                ),
            ],
            layout=W.Layout(width="100%", gap="6px"),
        )

        backend_row = form_row("Backend:", backend_dd)

        container_source_row = form_row("Source:", container_source)
        image_uri_row = form_row("Image:", image_uri)

        spack_enable_row = W.Box([spack_enable], layout=W.Layout(margin="0 0 0 120px"))
        spack_repo_row = form_row("Repo:", spack_repo_url)
        spack_dir_row = form_row("Dir name:", spack_dirname)
        spack_install_row = W.Box([spack_install_if_needed], layout=W.Layout(margin="0 0 0 120px"))
        spack_install_mode_row = form_row("Install:", spack_install_mode)
        spack_slurm_row = form_row("SLURM_DIR:", spack_slurm_dir)
        spack_pmix_row = form_row("PMIX_DIR:", spack_pmix_dir)

        exec_backend_inner = W.VBox([
            backend_row,
            container_source_row,
            image_uri_row,
            image_panel.container,
            software_panel.container,
            spack_enable_row,
            spack_repo_row,
            spack_dir_row,
            spack_env_row,
            # spack_slurm_row,
            # spack_pmix_row,
        ], layout=W.Layout(gap="8px"))

        def _toggle_exec_backend_ui(_=None):
            is_container = backend_dd.value == "container"
            is_oci = is_container and container_source.value in ("docker", "oci")

            container_source_row.layout.display = "flex" if is_container else "none"
            image_uri_row.layout.display = (
                "flex" if (is_container and not is_oci) else "none"
            )
            image_panel.set_visible(is_oci)
            software_panel.set_visible(is_container)

            spack_display = "none" if is_container else "flex"
            spack_box_display = "none" if is_container else "block"

            spack_enable_row.layout.display = spack_box_display
            spack_repo_row.layout.display = spack_display
            spack_dir_row.layout.display = spack_display
            spack_env_row.layout.display = spack_box_display
            spack_install_row.layout.display = "none"
            spack_install_mode_row.layout.display = "none"
            spack_slurm_row.layout.display = spack_display
            spack_pmix_row.layout.display = spack_display
        
        backend_dd.observe(_toggle_exec_backend_ui, names="value")
        container_source.observe(_toggle_exec_backend_ui, names="value")
        container_source.observe(update_visibility, names="value")
        _toggle_exec_backend_ui()

        # --- Remote + ICESEE-Spack environment lifecycle callbacks ---------
        def _setup_slurm_opts():
            return SetupSlurmOpts(
                partition=slurm_part.value.strip() or "cpu-small",
                time="08:00:00",
                nodes=1,
                ntasks=int(slurm_ntasks.value or 8),
                mem=slurm_mem.value.strip() or "32G",
                account=slurm_account.value.strip(),
                mail=slurm_mail.value.strip(),
            )

        def _spack_matlab_license(model):
            if model != "issm":
                return None
            return get_compute_profile(
                cluster_name_for_keys.value or "pace"
            ).matlab_license_config()

        spack_runtime = build_spack_runtime_callbacks(
            runtime_status=STATUS,
            log_output=log_out,
            status_widget=status_chip,
            status_html=status_html,
            bridge_factory=current_remote_bridge,
            ensure_connector_session=(
                lambda: (create_or_refresh_connector_session()
                         if should_use_connector() else None)
            ),
            env_badge=spack_env_badge,
            setup_job_label=spack_env_setup_label,
            view_log_button=spack_setup_log_btn,
            model_value=lambda: model_dd.value,
            remote_base_value=lambda: remote_base_dir.value.strip(),
            spack_dirname_value=lambda: spack_dirname.value.strip() or "ICESEE-Spack",
            spack_repo_value=lambda: (
                spack_repo_url.value.strip()
                or "https://github.com/ICESEE-project/ICESEE-Spack.git"
            ),
            setup_slurm_opts=_setup_slurm_opts,
            matlab_license_for=_spack_matlab_license,
        )
        spack_check_env_btn.on_click(spack_runtime.check)
        spack_prepare_env_btn.on_click(spack_runtime.prepare)
        spack_setup_log_btn.on_click(spack_runtime.view_setup_log)

        exec_backend_box = W.Accordion(children=[exec_backend_inner])
        exec_backend_box.set_title(0, "⚙️ Execution backend")
        exec_backend_box.selected_index = None

        remote_box = W.VBox([
            remote_conn_box,
            exec_backend_box,
            # Authentication, the connector card and the "Open Connector Setup"
            # action now live inside the Remote connection panel (B4).
            ssh_key_manager_box,
            slurm_box,
        ], layout=W.Layout(gap="10px"))

        run_plan = build_run_plan_panel(
            summary_widget=summary_html,
            command_widget=command_preview,
        )

        remote_log_controls = build_workspace_toolbar(
            [
                connect_btn,
                status_btn,
                # auto_tail_btn,
                tail_btn,
                clear_btn,
            ],
        )

        cloud_log_controls = build_workspace_toolbar(
            [
                cloud_smoke_btn,
                cloud_status_btn,
                cloud_logs_btn,
                clear_btn,
            ],
        )

        log_runtime_controls = build_workspace_toolbar([])

        run_settings_panel = build_run_settings_panel(
            configuration_rows=[
                ui_mode_row,
                *([agent_panel.container] if agent_panel is not None else []),
                mode_row,
                model_row,
                example_picker_row,
                example_info_row,
                example_row,
                exec_row,
                advanced_action_row,
                editor_panel.container,
                run_target_row,
                md_config_panel,
                icepack_config_panel,
                dataset_panel.container,
            ],
            remote_panel=remote_box,
            cloud_panel=cloud_box,
            run_plan=run_plan.container,
        )

        runtime_panel = build_runtime_panel(
            status_widget=status_chip,

            run_button=run_btn,
            # clear_button=clear_btn,

            # remote_connect_button=connect_btn,
            # remote_status_button=status_btn,
            # remote_logs_button=tail_btn,
            remote_terminate_button=terminate_btn,

            # cloud_status_button=cloud_status_btn,
            # cloud_logs_button=cloud_logs_btn,
            cloud_terminate_button=cloud_terminate_btn,
        )

        actions_card = runtime_panel.container

        # Compatibility aliases
        # remote_actions = runtime_panel.remote_actions
        # cloud_actions = runtime_panel.cloud_actions
        remote_actions = remote_log_controls
        cloud_actions = cloud_log_controls

        def _on_workspace_run_selected(_run_id):
            visualization_panel.controller.refresh()
            # C6: if a still-running cloud run is selected (e.g. after a kernel
            # restart) and nothing is polling it, resume the auto-poll.
            run = workspace_manager.selected_run()
            ctl = _cloud["controller"]
            if (run is not None and run.execution_mode == "cloud"
                    and ctl is not None and ctl.job_id != str(run.jobid or "")):
                meta = run.metadata or {}
                _rc = run.container or {}
                ctl.attach(
                    job_id=str(run.jobid or ""),
                    s3_run=str(meta.get("cloud_run") or run.remote_directory or ""),
                    model=run.model, region=meta.get("region") or "",
                    profile=meta.get("profile"),
                    account_id=meta.get("account_id") or "",
                    example=meta.get("example") or "",
                    run_target=meta.get("run_target") or "",
                    source=meta.get("source") or "",
                    vcpu=meta.get("vcpu") or 0,
                    memory_gib=meta.get("memory_gib") or 0,
                    expected_runtime_minutes=meta.get("expected_runtime_minutes") or 0,
                    cost_public=meta.get("cost_estimate") or {},
                    image_key=meta.get("image_key") or "",
                    image_label=meta.get("image_label") or "",
                    image_reference=(meta.get("image_reference")
                                     or (_rc.get("reference") or "").replace("docker://", "")),
                    image_digest=meta.get("image_digest") or _rc.get("digest") or "",
                    aws_resources=meta.get("aws_resources") or {},
                    state={"submitted": "queued"}.get(run.status, run.status),
                )

        # Runs is the selection/control surface; Files / Run Log / Results are
        # views of the SAME selected run. The Selected-Run actions route through
        # the existing Workspace machinery: switch the existing Tab, then invoke
        # the existing tail / preview path for the selected run. No second
        # panel, no second viewer, no second result-loading path.
        _workspace_tabs = {"w": None}       # late-bound: set after build_run_details
        _WS_TAB = {"runs": 0, "files": 1, "log": 2, "results": 3}

        def _switch_workspace_tab(name):
            tab = _workspace_tabs["w"]
            idx = _WS_TAB.get(name)
            if tab is not None and idx is not None and idx < len(tab.children):
                tab.selected_index = idx

        def _runs_tail_log():
            rid = workspace_history_panel.runs.value
            if not rid:
                return
            workspace_manager.select_run(rid)          # shared selected run
            _switch_workspace_tab("log")
            workspace_manager.tail(rid)                # existing tail machinery

        def _runs_show_figures():
            rid = workspace_history_panel.runs.value
            if not rid:
                return
            workspace_manager.select_run(rid)
            _switch_workspace_tab("results")
            on_results_preview()                      # existing ResultPackage / Visualizer

        def _runs_download():
            rid = workspace_history_panel.runs.value
            if not rid:
                return
            workspace_manager.select_run(rid)
            on_results_download()                     # download only -- no tab switch

        with perf.span("history panel"):
            workspace_history_panel = build_workspace_history_panel(
                manager=workspace_manager,
                on_run_selected=_on_workspace_run_selected,
                defer_initial_load=True,   # list runs now; inspect on selection
                on_tail_log=_runs_tail_log,
                on_show_figures=_runs_show_figures,
                on_download=_runs_download,
            )

        output_workspace = build_run_details(
            log_output=log_out,
            results_output=results_out,
            download_controls=download_buttons_row,
            log_controls=log_runtime_controls,
            runs_panel=workspace_history_panel.runs_panel,
            files_panel=workspace_history_panel.files_panel,
            visualization_panel=visualization_panel.container,
        )
        _workspace_tabs["w"] = output_workspace.tabs

        # -- CLOUD RUN active-run surface (C7.5) --------------------------
        # The card's [View log] / [View results] route into the SAME Workspace
        # tabs + tail/preview machinery the Runs panel uses -- no second log
        # viewer, no second results path.
        from cryostack_src.frontend.cryolauncher.cloud_active_run_runtime import (
            build_active_run_callbacks,
        )

        def _run_id_for_job(job_id):
            job_id = str(job_id or "")
            if not job_id:
                return None
            for run in workspace_manager.list_runs():
                if str(getattr(run, "jobid", "")) == job_id:
                    return run.id
            return None

        def _open_active_run(tab):
            rid = _run_id_for_job(STATUS.get("batch_job_id"))
            if rid:
                workspace_manager.select_run(rid)
            _switch_workspace_tab(tab)
            if tab == "log":
                if rid:
                    workspace_manager.tail(rid)
                else:
                    on_cloud_logs()
            else:
                on_results_preview()

        _active_run = build_active_run_callbacks(
            widgets=cloud_environment,
            on_view_log=lambda: _open_active_run("log"),
            on_view_results=lambda: _open_active_run("results"),
            on_terminate=on_cloud_terminate_confirm,
        )
        _active_run_holder["render"] = _active_run.render

        workspace_ui = build_workspace_explorer(
            run_settings=run_settings_panel,
            runtime=actions_card,
            run_details=output_workspace.container,
        )

        row = workspace_ui.container
        workspace_height_sync = workspace_ui.height_sync

        auto_tail_btn.observe(on_auto_tail_change, names="value")

        def _toggle_auth_widgets(_=None):
            show = (auth_mode.value == "bootstrap")
            cluster_password.layout.display = "block" if show else "none"
            bootstrap_btn.layout.display = "block" if show else "none"

        auth_mode.observe(_toggle_auth_widgets, names="value")

        _toggle_auth_widgets()
        with perf.span("example discovery"):
            refresh_example_picker()
            apply_selected_example()

        # B2: restore this user's saved per-resource settings. Runs last, after
        # every widget + observer exists; the controller guards persistence so a
        # blank build state can never overwrite stored settings during restore.
        try:
            with perf.span("workspace hydrate"), ui_refresh.batch():
                _b2_warnings = resource_state.hydrate()
                _sync_resource_facts()
            for _w in _b2_warnings:
                with log_out:
                    print("[settings]", _w)
        except Exception as _b2_err:  # never block the gateway on restore
            with log_out:
                print("[settings] restore skipped:", type(_b2_err).__name__, _b2_err)

        # Run Assistant (Beta) is now the third interaction mode ("Agent"),
        # opt-in via CRYOSTACK_AGENT_PANEL and built inline with the Run
        # Settings (see _build_agent_panel / update_visibility). Nothing
        # agent-related renders unless the user selects Agent mode.

        page = W.VBox(
            [
                shared_styles,
                # W.HTML(css),
                auto_scroll_script,
                W.HTML(CRYOSTACK_FRONTEND_CSS),

                experiment_bridge.widget(),
                workspace_bridge.widget(),

                app_menu,
                header,
                row,
                workspace_height_sync,
                # actions_card,
                back_link,
            ],
            layout=W.Layout(width="100%"),
        )
        page.add_class("cryostack-application-page")

        image_panel.set_model(model_dd.value)
        image_panel.set_profile(software_panel.profile())
        update_visibility()
        update_summary()

        perf.mark("gateway total (icesheets)", _time.perf_counter() - _perf_t0)
        return page

    except Exception as e:
        import traceback
        print("ERROR:", e)
        traceback.print_exc()
        raise
