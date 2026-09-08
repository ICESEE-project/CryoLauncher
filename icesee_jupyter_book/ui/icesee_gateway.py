# icesee_jupyter_book/ui/icesee_gateway.py
from __future__ import annotations

import os
import time as _time
import uuid
import html as html_lib
import yaml
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
import ipywidgets as W

from IPython.display import display, Image

import zipfile
import shutil
import base64
import tarfile
import tempfile
from IPython.display import HTML, FileLink

from icesee_jupyter_book.core.connector_relay_client import (
    create_session,
    check_status as relay_check_status,
    send_command,
)

from icesee_jupyter_book.core import ssh_key_manager
from icesee_jupyter_book.core.example_registry import EXAMPLES, enabled_names
from cryostack_src.workspace import resolve_workspace_user, user_run_root, read_manifest
from cryostack_src.resources.profiles import get_compute_profile, initial_remote_fields
from cryostack_src.remote import RemoteBridge
from cryostack_src.remote.access_state import (
    enforce_remote_access,
    verify_remote_identity,
    identity_result_from_output,
    can_reuse_connectivity_identity,
    classify_ssh_failure,
    SSH_KEY_NOT_AUTHORIZED,
)
from icesee_jupyter_book.core.config_io import load_yaml, dump_yaml
from icesee_jupyter_book.core.example_discovery import (
    find_run_script,
    find_params_template,
    find_report_notebook,
)
from icesee_jupyter_book.core.local_runner import (
    run_dir,
    run_local_example,
    LocalRunResult,
)
from icesee_jupyter_book.core.remote_runner import (
    ssh_run,
    render_slurm_script,
    ensure_local_ssh_key,
    remote_install_pubkey_with_password,
    explain_ssh_failure_hint,
    remote_test_connection,
    remote_job_status,
    remote_tail_log,
    remote_cancel_job,
    submit_remote_example,
    submit_remote_example_container,
    bootstrap_passwordless_ssh,
    connector_ssh,
    connector_fetch_archive,
    submit_remote_example_via_connector,
    submit_remote_example_container_via_connector,
    connector_get_public_key,
    RemoteSubmitResult,
)
from icesee_jupyter_book.core import run_records
from icesee_jupyter_book.core.runs_manager import IceseeRunsManager
from icesee_jupyter_book.core.results_package import discover_result_package
from icesee_jupyter_book.core.cloud_bridge_adapter import (
    IceseeCloudBridgeConfig,
    build_icesee_cloud_bridge,
    icesee_cloud_status,
    icesee_cloud_terminate,
    submit_icesee_cloud_run,
)
from cryostack_src.cloud.diagnostics import merge_aws_resources, resources_from_poll
from icesee_jupyter_book.core.run_records import da_identity_from_params
from cryostack_src.frontend.cryolauncher.panels.run_plan import build_run_plan_panel
from cryostack_src.frontend.cryolauncher.panels.run_settings import build_run_settings_panel
from cryostack_src.frontend.cryolauncher.panels.runtime_panel import build_runtime_panel
from cryostack_src.frontend.cryolauncher.workspace.run_history import (
    build_workspace_history_panel,
)
from cryostack_src.frontend.cryolauncher.workspace.run_details import build_run_details
from cryostack_src.frontend.cryolauncher.workspace.explorer import build_workspace_explorer
from cryostack_src.frontend.cryolauncher.workspace.toolbar import build_workspace_toolbar

from icesee_jupyter_book.ui.shared_ssh_widgets import build_ssh_key_manager

from icesee_jupyter_book.ui.application_menus import (
    build_icesee_app_menu,
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
from icesee_jupyter_book.ui.shared_validation import validate_slurm_resources
from icesee_jupyter_book.ui.shared_observer_guard import UIRefreshCoordinator
from cryostack_src import perf

from icesee_jupyter_book.ui.application_menus import (
    build_icesee_app_menu,
    load_cryostack_account_assets,
)

from icesee_jupyter_book.ui.shared_app_styles import (
    shared_application_styles,
)

from icesee_jupyter_book.ui.experiment_bridge import (
    ExperimentBridge,
    load_experiment_bridge,
)

import getpass

from icesee_jupyter_book.ui.workspace_bridge import (
    WorkspaceBridge,
    load_workspace_bridge,
)
from icesee_jupyter_book.ui.workspace_persistence import make_state_io
from cryostack_src.workspace.resource_state import (
    ResourceStateController,
    strip_secrets,
)

from icesee_jupyter_book.core.experiment_status import (
    experiment_update_from_job_status,
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

# ===========================================================
# local reporting helpers (also used by remote when fetching results)
# ===========================================================

def refresh_results_preview(rd: Path, results_out: W.Output):
    results_out.clear_output()
    with results_out:
        fig_dir = rd / "figures"
        pngs = sorted(fig_dir.glob("*.png"))
        if not pngs:
            pngs = sorted((rd / "results").glob("*.png"))
        h5s = sorted((rd / "results").glob("*.h5"))

        print("Run folder:", rd)
        print(f"Results: {len(h5s)} H5, {len(pngs)} PNG\n")
        for p in h5s[:10]:
            print(" -", p.name)

        if pngs:
            print("\nFigures:")
            for p in pngs[:6]:
                display(Image(filename=str(p)))
        else:
            print("\nNo figures found yet.")


def make_zip_from_dir(src_dir: Path, zip_path: Path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src_dir.rglob("*")):
            if p.is_file():
                zf.write(p, arcname=p.relative_to(src_dir))

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

app_menu = build_icesee_app_menu()
shared_styles = shared_application_styles()

# ============================================================
# UI builder (single entry point)
# ============================================================
def build_icesee_ui():
    _perf_t0 = _time.perf_counter()
    try:
        load_cryostack_account_assets()
        load_experiment_bridge()
        load_workspace_bridge()

        shared_styles = shared_application_styles()

        experiment_bridge = ExperimentBridge()
        workspace_bridge = WorkspaceBridge()

        # -----------------------------
        # UI state containers
        # -----------------------------
        STATUS = {"mode": "idle", "remote_dir": None, "jobid": None, "batch_job_id": None, "s3_run": None}

        SESSION = {
            "id": None,
            "ws_url": None,
        }

        def set_status(state: str):
            cls = {"idle": "icesee-idle", "running": "icesee-running", "done": "icesee-done", "fail": "icesee-fail"}[state]
            label = {"idle": "Idle", "running": "Running…", "done": "Done", "fail": "Failed"}[state]
            status_chip.value = f"<span class='icesee-status {cls}'>{label}</span>"

        # -----------------------------
        # Top controls
        # -----------------------------
        example_dd = W.Dropdown(options=enabled_names(), value=enabled_names()[0], layout=W.Layout(width="320px"))
        preset_dd = W.Dropdown(options=["Default"], value="Default", layout=W.Layout(width="320px"))

        filter_alg_dd = W.Dropdown(
            options=[("EnKF", "EnKF"), ("DEnKF", "DEnKF"), ("EnTKF", "EnTKF"), ("EnRSKF", "EnRSKF")],
            value="EnKF",
            layout=W.Layout(width="320px"),
        )

        output_label_dd = W.Dropdown(
            options=[("true-wrong (demo output)", "true-wrong"), ("EnKF (output name)", "enkf")],
            value="true-wrong",
            layout=W.Layout(width="320px"),
        )

        ens_sl = W.IntSlider(min=1, max=200, value=30, layout=W.Layout(width="320px"), continuous_update=False)
        seed_in = W.IntText(value=1, layout=W.Layout(width="320px"))

        gen_report = W.Checkbox(value=True, description="Generate report (read_results.ipynb)")
        open_latest = W.Checkbox(value=False, description="After run: open latest run folder")

        # run_btn = W.Button(description="Run", button_style="success", icon="play")
        action_btn = W.Button(description="Run", button_style="success", icon="play")
        clear_btn = W.Button(description="Clear", button_style="", icon="trash")
        

        status_chip = W.HTML("<span class='icesee-status icesee-idle'>Idle</span>")
        log_out = W.Output(layout=W.Layout(
            border="1px solid rgba(0,0,0,.12)",
            padding="10px",
            height="360px",
            overflow="auto",
            width="100%"
        ))

        results_out = W.Output(layout=W.Layout(
            border="1px solid rgba(0,0,0,.12)",
            padding="10px",
            height="620px",
            overflow="auto",
            width="100%"
        ))

        # -----------------------------
        # Mode Tabs
        # -----------------------------
        MODE_LOCAL, MODE_REMOTE, MODE_CLOUD = "local", "cluster", "cloud"
        mode_tabs = W.Tab()
        mode_tabs.layout = W.Layout(width="100%")
        mode_tabs.layout.flex = "1 1 auto"
        mode_tabs.layout.min_width = "0"

        def get_mode():
            return {0: MODE_LOCAL, 1: MODE_REMOTE, 2: MODE_CLOUD}.get(mode_tabs.selected_index, MODE_LOCAL)
        
        def update_action_button():
            mode = get_mode()
            if mode == MODE_LOCAL:
                action_btn.description = "Run"
                action_btn.icon = "play"
                action_btn.button_style = "success"
            elif mode == MODE_REMOTE:
                action_btn.description = "Submit (Remote)"
                action_btn.icon = "server"
                action_btn.button_style = "warning"
            else:
                action_btn.description = "Submit (Cloud)"
                action_btn.icon = "cloud-upload"
                action_btn.button_style = "warning"

        def on_action_click(_=None):
            # simple anti-double-submit (optional but recommended)
            if STATUS.get("_busy"):
                with log_out:
                    print("[ui] Busy — ignoring extra click.")
                return

            STATUS["_busy"] = True
            action_btn.disabled = True
            try:
                mode = get_mode()
                if mode == MODE_LOCAL:
                    return run_example_local()
                elif mode == MODE_REMOTE:
                    return run_example_remote_submit()
                else:
                    return run_example_cloud_submit()
            finally:
                action_btn.disabled = False
                STATUS["_busy"] = False

        # =========================================================
        # Params UI (auto from template)
        # =========================================================
        params_holder = W.VBox([])
        params_accordion = None
        PARAMS0 = {}
        WIDGETS = {}
        EXTRA_YAML = {}
        RUN_SCRIPT = None
        TEMPLATE = None
        REPORT_NB = None

        def build_params_ui(template_path: Path):
            nonlocal params_accordion, PARAMS0, WIDGETS, EXTRA_YAML
            PARAMS0 = load_yaml(template_path)
            WIDGETS = {}
            EXTRA_YAML = {}

            children, titles = [], []

            for sec, sec_dict in (PARAMS0 or {}).items():
                titles.append(sec)
                sec_widgets = {}
                rows = []

                if isinstance(sec_dict, dict):
                    for k, v in sec_dict.items():
                        w = widget_for(k, v)
                        sec_widgets[k] = w
                        rows.append(
                            W.HBox(
                                [W.HTML(f"<div class='icesee-k'>{k}</div>"), w],
                                layout=W.Layout(gap="12px"),
                            )
                        )

                    extra = W.Textarea(
                        value="# Add future keys here (YAML)\n",
                        layout=W.Layout(width="100%", height="90px"),
                    )
                    EXTRA_YAML[sec] = extra
                    rows.append(W.HTML("<div class='icesee-subtle' style='margin-top:6px'>Extra keys (optional)</div>"))
                    rows.append(extra)
                else:
                    w = W.Textarea(
                        value=yaml.safe_dump(sec_dict, sort_keys=False).strip(),
                        layout=W.Layout(width="100%", height="140px"),
                    )
                    sec_widgets["__raw__"] = w
                    rows.append(w)

                WIDGETS[sec] = sec_widgets
                children.append(W.VBox(rows, layout=W.Layout(gap="8px")))

            params_accordion = W.Accordion(children=children)
            for i, t in enumerate(titles):
                params_accordion.set_title(i, t)

        def sync_quick_into_widgets():
            sec = None
            for candidate in ["enkf-parameters", "enkf_parameters", "enkf"]:
                if candidate in WIDGETS:
                    sec = candidate
                    break
            if not sec:
                return

            if "Nens" in WIDGETS[sec]:
                WIDGETS[sec]["Nens"].value = int(ens_sl.value)
            if "seed" in WIDGETS[sec]:
                WIDGETS[sec]["seed"].value = int(seed_in.value)
            if "filter_type" in WIDGETS[sec]:
                WIDGETS[sec]["filter_type"].value = str(filter_alg_dd.value)

        def build_config_from_widgets() -> dict:
            cfg = {}
            for sec, sw in WIDGETS.items():
                if "__raw__" in sw:
                    cfg[sec] = yaml.safe_load(sw["__raw__"].value)
                    continue

                cfg[sec] = {}
                for k, w in sw.items():
                    if k == "__raw__":
                        continue
                    cfg[sec][k] = read_widget(w)

                extra = EXTRA_YAML.get(sec)
                if extra:
                    txt = extra.value.strip()
                    if txt and not txt.startswith("#"):
                        extra_obj = yaml.safe_load(txt) or {}
                        if isinstance(extra_obj, dict):
                            cfg[sec].update(extra_obj)
                        else:
                            cfg[sec]["__extra__"] = extra_obj
            return cfg

        # -----------------------------
        # Rebuild on example change
        # -----------------------------
        def rebuild_for_example(_=None):
            nonlocal RUN_SCRIPT, TEMPLATE, REPORT_NB
            cfg = EXAMPLES[example_dd.value]
            RUN_SCRIPT = find_run_script(cfg)
            TEMPLATE = find_params_template(cfg)
            REPORT_NB = find_report_notebook(cfg)

            build_params_ui(TEMPLATE)
            params_holder.children = (params_accordion,)

            with log_out:
                print("[Loaded]")
                print("Template:", TEMPLATE)
                print("Runner  :", RUN_SCRIPT)
                print("Report  :", REPORT_NB if REPORT_NB else "(none)")

        example_dd.observe(rebuild_for_example, names="value")

        # =========================================================
        # Remote panel widgets
        #
        # Ownership: RESOURCE facts (host, port, partition, wall time) come from
        # the ComputeProfile; USER x RESOURCE / USER fields (HPC username, remote
        # directory, Slurm account, notification email) are BLANK until B2 and
        # are never taken from the Voila service account's environment.
        # =========================================================
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

        auth_mode = W.ToggleButtons(
        options=[("Key-only", "key"), ("Bootstrap with password (one-time)", "bootstrap")],
        value="key",
        layout=W.Layout(width="auto", max_width="100%")
        )

        cluster_password = W.Password(
            value="",
            placeholder="One-time password (not stored)",
            layout=W.Layout(width="320px")
        )

        bootstrap_btn = W.Button(
            description="Enable passwordless SSH",
            icon="key",
            button_style="warning"
        )

        remote_base_dir = W.Text(value=_rf["remote_directory"], placeholder="your remote working directory (required)", layout=W.Layout(width="320px"))
        remote_tag = W.Text(value="icesee", layout=W.Layout(width="220px"))

        exec_backend_choice = W.Dropdown(
            options=[("ICESEE-Spack", "spack"), ("ICESEE-Container", "container")],
            value="spack",
            layout=W.Layout(width="320px"),
        )

        container_source = W.Dropdown(
            options=[("Docker Hub", "docker"), ("AWS Registry", "aws")],
            value="docker",
            layout=W.Layout(width="220px"),
        )

        access_mode_dd = W.Dropdown(
            options=[
                ("CryoStack Connector (recommended)", "connector"),
                ("Direct SSH from server (shared-trust / developer)", "direct"),
                ("Auto", "auto"),
            ],
            value="connector",
            layout=W.Layout(width="320px"),
        )

        relay_status = W.HTML("")
        connector_setup_link = W.HTML("")

        start_connector_session_btn = W.Button(
            description="Create connector session",
            icon="plug",
            button_style="info",
        )

        container_image_uri = W.Text(
            value="icesee/combined-container:latest",
            layout=W.Layout(width="520px"),
        )

        connect_btn = W.Button(description="Test SSH", icon="terminal", button_style="info")
        submit_btn = W.Button(description="Submit job", icon="server", button_style="warning")
        status_btn = W.Button(description="Check status", icon="tasks", button_style="")
        tail_btn = W.Button(description="Tail log", icon="file-text", button_style="")
        terminate_btn = W.Button(description="Terminate job",icon="stop",button_style="danger")

        preview_results_btn = W.Button(
            description="Preview results",
            icon="eye",
            button_style="info",
        )

        results_download_btn = W.Button(
            description="Download results",
            icon="download",
            button_style="success",
        )

        slurm_job_name = W.Text(value="ICESEE", layout=W.Layout(width="100%"))              # RUN
        slurm_time = W.Text(value=_rf["wall_time"], layout=W.Layout(width="100%"))           # RESOURCE default

        slurm_nodes = W.IntText(value=2, layout=W.Layout(width="100%"))                      # RUN
        slurm_ntasks = W.IntText(value=24, layout=W.Layout(width="100%"))                    # RUN
        slurm_tpn = W.IntText(value=24, layout=W.Layout(width="100%"))                       # RUN

        slurm_part = W.Text(value=_rf["partition"], layout=W.Layout(width="100%"))           # RESOURCE default
        slurm_mem = W.Text(value="256G", layout=W.Layout(width="100%"))                             # RUN
        slurm_account = W.Text(                                                                     # USER x RESOURCE -- blank
            value=_rf["slurm_account"],
            placeholder=("Slurm allocation (required for this resource)"
                         if _rf["account_required"] else "Slurm allocation"),
            layout=W.Layout(width="100%"),
        )
        slurm_mail = W.Text(                                                                        # USER -- blank
            value=_rf["notification_email"],
            placeholder="notification email (optional)",
            layout=W.Layout(width="100%"),
        )

        cluster_mpi_np = W.IntText(value=40, layout=W.Layout(width="100%"))
        cluster_model_nprocs = W.IntText(value=4, layout=W.Layout(width="100%"))

        def _icesee_run_dir_base() -> Path:
            """Per-user, per-app run root -- two authenticated CryoStack users
            never share a run directory (the process-global BOOK/icesee_runs/
            did). Falls back to the default location for an unauthenticated
            session."""
            try:
                return user_run_root(app="icesee")
            except Exception:
                return None   # local_runner.run_dir() then uses its default

        def _new_icesee_run_id() -> str:
            return datetime.now().strftime("%Y%m%d_%H%M%S") + "-" + uuid.uuid4().hex[:6]

        def _record_icesee_run(
            *, run_dir, run_id, params, example, execution_mode, backend,
            source="", run_target="", model_environment="", status="running",
            jobid=None, remote_directory=None,
        ):
            """Write a local .cryostack-run.json manifest for this ICESEE run
            (run_records.record_run) without ever letting a manifest failure
            interrupt the real run -- a warning in the log is the worst case."""
            try:
                return run_records.record_run(
                    run_dir=run_dir, run_id=run_id,
                    name=f"ICESEE {example} ({execution_mode})",
                    params=params, example=example, execution_mode=execution_mode,
                    backend=backend, source=source, run_target=run_target,
                    model_environment=model_environment, status=status,
                    jobid=jobid, remote_directory=remote_directory,
                )
            except Exception as _e:
                with log_out:
                    print("[history][WARN] could not record run:", type(_e).__name__, _e)
                return None

        def _update_icesee_run(run_dir, **kwargs):
            """Update a previously recorded ICESEE run manifest. Same
            never-break-the-run contract as _record_icesee_run."""
            try:
                return run_records.update_run(run_dir, **kwargs)
            except Exception as _e:
                with log_out:
                    print("[history][WARN] could not update run history:", type(_e).__name__, _e)
                return None

        def _merge_icesee_aws_resources(run_dir_path, updates: dict) -> None:
            """Merge ``updates`` into this run's persisted metadata['aws_resources']
            (cryostack_src.cloud.diagnostics.merge_aws_resources: non-secret keys
            only, never overwrites a known value with an empty one) so the
            reused Workspace history panel's AWS-diagnostics console links work
            for ICESEE cloud runs too -- the same pure snapshot mechanism
            CryoLauncher's cloud runs already use."""
            try:
                manifest = Path(run_dir_path) / run_records.MANIFEST_NAME
                existing = read_manifest(manifest).metadata.get("aws_resources") if manifest.is_file() else None
            except Exception:
                existing = None
            merged = merge_aws_resources(existing, updates)
            _update_icesee_run(run_dir_path, extra_metadata={"aws_resources": merged})

        def local_remote_cache_dir() -> Path:
            rd = run_dir(_icesee_run_dir_base(), _new_icesee_run_id())
            return rd / "_remote_fetch"


        def fetch_remote_outputs_to_local() -> Path | None:
            rdir = STATUS.get("remote_dir")
            if not rdir:
                with results_out:
                    print("[results] No remote run directory found. Submit a job first.")
                return None

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            local_cache = local_remote_cache_dir()
            outputs_dir = local_cache / "outputs"

            if outputs_dir.exists():
                shutil.rmtree(outputs_dir)
            outputs_dir.mkdir(parents=True, exist_ok=True)

            remote_outputs = f"{str(rdir).rstrip('/')}/outputs"

            if access_mode_dd.value == "connector":
                if not SESSION.get("id"):
                    create_or_refresh_connector_session()

                result = connector_fetch_archive(
                    SESSION["id"],
                    host,
                    user,
                    port,
                    f"{remote_outputs.rstrip('/')}/",
                    timeout=600,
                )

                if not result.get("ok"):
                    with results_out:
                        print("[results][ERROR] Could not fetch remote outputs through connector.")
                        print("Remote source:", remote_outputs)
                        print(result)
                    return None

                archive_b64 = result.get("archive_b64")
                if not archive_b64:
                    with results_out:
                        print("[results][ERROR] Connector response did not include archive_b64.")
                    return None

                with tempfile.TemporaryDirectory() as td:
                    archive_path = Path(td) / "outputs.tar.gz"
                    archive_path.write_bytes(base64.b64decode(archive_b64))

                    with tarfile.open(archive_path, "r:gz") as tar:
                        tar.extractall(outputs_dir)

                return outputs_dir

            rsync_cmd = [
                "rsync",
                "-az",
                "-e",
                f"ssh -p {port}",
                f"{user}@{host}:{remote_outputs.rstrip('/')}/",
                f"{outputs_dir}/",
            ]

            rs = subprocess.run(rsync_cmd, capture_output=True, text=True)

            if rs.returncode != 0:
                with results_out:
                    print("[results][ERROR] Could not fetch remote outputs.")
                    print("Remote source:", remote_outputs)
                    print("--- stdout ---")
                    print(rs.stdout)
                    print("--- stderr ---")
                    print(rs.stderr)
                return None

            return outputs_dir
        

        def preview_remote_results(_=None):
            results_out.clear_output()

            outputs_dir = fetch_remote_outputs_to_local()
            if outputs_dir is None:
                return

            pngs = sorted(outputs_dir.rglob("*.png"))
            h5s = sorted(outputs_dir.rglob("*.h5"))
            all_files = sorted([p for p in outputs_dir.rglob("*") if p.is_file()])

            with results_out:
                print("Fetched outputs:", outputs_dir)
                print(f"H5 files: {len(h5s)}")
                print(f"PNG figures: {len(pngs)}\n")

                if all_files:
                    print("Output tree:")
                    for p in all_files[:50]:
                        print(" -", p.relative_to(outputs_dir))
                    print()

                if pngs:
                    print("Preview figures:")
                    for p in pngs[:8]:
                        print("\n", p.name)
                        display(Image(filename=str(p)))
                else:
                    print("No PNG figures found.")


        def download_results_bundle(_=None):
            results_out.clear_output()

            outputs_dir = fetch_remote_outputs_to_local()
            if outputs_dir is None:
                return

            zip_path = local_remote_cache_dir() / "results_bundle.zip"

            if zip_path.exists():
                zip_path.unlink()

            make_zip_from_dir(outputs_dir, zip_path)

            with results_out:
                print("Results bundle ready:")
                display(FileLink(str(zip_path)))
            

        def form_pair(label: str, widget, label_width: str = "80px", widget_width: str = "1fr"):
            lbl = W.HTML(f"<div class='icesee-lbl-sm'>{label}</div>")
            lbl.layout = W.Layout(width=label_width, min_width=label_width)
            widget.layout = W.Layout(width="100%")
            box = W.HBox([lbl, widget], layout=W.Layout(align_items="center", gap="8px", width="100%"))
            return box

        # minimal module/export lines (you can expand later)
        remote_module_lines = W.Textarea(
            value="# module load ...\n",
            layout=W.Layout(width="100%", height="80px"),
        )
        remote_export_lines = W.Textarea(
            value="# export ISSM_DIR=...\n",
            layout=W.Layout(width="100%", height="80px"),
        )

        remote_backend = W.ToggleButtons(
            options=[("SSH (Slurm)", "ssh"), ("HTTPS (Webhook)", "https")],
            value="ssh",
            layout=W.Layout(width="320px")
        )

        https_base = W.Text(value="", placeholder="https://your-service.example.com", layout=W.Layout(width="520px"))
        https_submit_path = W.Text(value="/submit", layout=W.Layout(width="260px"))
        https_status_path = W.Text(value="/status", layout=W.Layout(width="260px"))  # will call /status/<run_id>
        https_tail_path   = W.Text(value="/tail", layout=W.Layout(width="260px"))    # will call /tail/<run_id>?n=120
        https_health_path = W.Text(value="/health", layout=W.Layout(width="260px"))

        https_token = W.Password(value="", placeholder="optional bearer token", layout=W.Layout(width="320px"))
        https_headers = W.Textarea(
            value="# optional extra headers (YAML dict)\n# X-API-Key: abc\n",
            layout=W.Layout(width="100%", height="80px")
        )

        https_webhook_box = W.VBox([
        W.HTML("<div class='icesee-subtle'>HTTPS backend (user-provided webhook/service)</div>"),
        W.HBox([W.HTML("<div class='icesee-lbl'>Base URL:</div>"), https_base], layout=W.Layout(gap="12px")),
        W.HBox([W.HTML("<div class='icesee-lbl'>Paths:</div>"),
                https_submit_path, https_status_path, https_tail_path, https_health_path],
            layout=W.Layout(gap="8px")),
        W.HBox([W.HTML("<div class='icesee-lbl'>Token:</div>"), https_token], layout=W.Layout(gap="12px")),
        W.HTML("<div class='icesee-subtle'>Extra headers (YAML)</div>"),
        https_headers,
        ], layout=W.Layout(gap="8px"))

        ood_cluster = W.Dropdown(
            options=[
                ("Phoenix OnDemand", "https://ondemand-phoenix.pace.gatech.edu/pun/sys/dashboard/"),
                ("Hive OnDemand",    "https://ondemand-hive.pace.gatech.edu/pun/sys/dashboard/"),
                ("ICE OnDemand",     "https://ondemand-ice.pace.gatech.edu/pun/sys/dashboard/"),
            ],
            value="https://ondemand-phoenix.pace.gatech.edu/pun/sys/dashboard/",
            layout=W.Layout(width="520px")
        )

        open_ood_btn = W.Button(description="Open OnDemand", icon="external-link", button_style="info")

        # --- ICESEE-Spack bootstrap ---
        spack_enable = W.Checkbox(value=True, description="Use ICESEE-Spack on Remote")
        spack_repo_url = W.Text(
            value="https://github.com/ICESEE-project/ICESEE-Spack.git",
            layout=W.Layout(width="520px"),
        )
        spack_dirname = W.Text(value="ICESEE-Spack", layout=W.Layout(width="220px"))

        spack_install_if_needed = W.Checkbox(value=False, description="Run install.sh if not installed")
        spack_install_mode = W.Dropdown(
            options=[
                ("Default", ""),
                ("With ISSM", "--with-issm"),
                ("With Firedrake", "--with-firedrake"),
                ("With Icepack", "--with-icepack"),
            ],
            value="--with-issm",
            layout=W.Layout(width="220px"),
        )

        # README mentions SLURM_DIR + PMIX_DIR for install.sh
        spack_slurm_dir = W.Text(value="", placeholder="e.g. /opt/slurm/current", layout=W.Layout(width="320px"))
        spack_pmix_dir  = W.Text(value="", placeholder="e.g. /opt/pmix/5.0.1", layout=W.Layout(width="320px"))

        # Optional: use an existing sbatch from the repo if present
        spack_use_existing_sbatch = W.Checkbox(
            value=True,
            description="If run_job_spack.sbatch exists for this example, submit it",
        )

        ssh_box = W.VBox([
        # existing SSH fields: host/user/port/auth/... and buttons
        ])

        ondemand_box = W.VBox([
            W.HTML("<div class='icesee-subtle'>OnDemand (web portal)</div>"),
            W.HBox([W.HTML("<div class='icesee-lbl'>Portal:</div>"), ood_cluster], layout=W.Layout(gap="12px")),
            W.HBox([open_ood_btn], layout=W.Layout(gap="10px")),
            W.HTML("<div class='icesee-subtle'>Tip: You may need GT VPN to access OnDemand.</div>"),
        ])

        def create_or_refresh_connector_session(_=None):
            log_out.clear_output()

            try:
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
                    <a href="https://cryostack.eas.gatech.edu/connect/?session={SESSION['id']}&app=icesee"
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
                  (“Pair with CryoStack…”). One-time; expires with this session.
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

        def _toggle_remote_backend(_=None):
            is_ssh = (remote_backend.value == "ssh")
            ssh_box.layout.display = "block" if is_ssh else "none"
            ondemand_box.layout.display = "none" if is_ssh else "block"

        remote_backend.observe(_toggle_remote_backend, names="value")

        def _sync_resource_facts(_=None):
            # RESOURCE facts follow the selected resource; personal fields
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
            workspace_bridge, "icesee",
            resolve_workspace_user(require_authenticated=False).user_id,
        )
        resource_state = ResourceStateController(
            load_state=_b2_load, save_state=_b2_save,
            read_personal=_b2_read_personal, apply_personal=_b2_apply_personal,
            resource_name=lambda: cluster_name_for_keys.value,
            set_resource_name=lambda n: setattr(cluster_name_for_keys, "value", n),
            service_username=(os.environ.get("USER") or getpass.getuser() or ""),
        )

        # shared observer-suppression primitive: a resource switch / B2
        # hydration is one batch of programmatic .value = ... assignments, not
        # a dozen independent observer fan-outs.
        ui_refresh = UIRefreshCoordinator()

        def _on_resource_changed(change):
            with ui_refresh.batch():
                resource_state.switch_resource(change.get("old"), change.get("new"))
                _sync_resource_facts()

        cluster_name_for_keys.observe(_on_resource_changed, names="value")
        _toggle_remote_backend()
        W.HBox([W.HTML("<div class='icesee-lbl'>Backend:</div>"), remote_backend], layout=W.Layout(gap="12px")),
        ssh_box,
        ondemand_box,

        def on_test_remote(_=None):
            log_out.clear_output()
            set_status("running")

            if remote_backend.value == "https":
                with log_out:
                    print("[remote:https] OnDemand portal:", ood_cluster.value)
                    print("Open it in a browser tab (VPN may be required).")
                set_status("done")
                return

            # else: your SSH test (with timeout) as you already fixed
            return run_example_remote_test()
        # connect_btn.on_click(on_test_remote)

        def submit_remote(_=None):
            log_out.clear_output()
            set_status("running")

            if remote_backend.value == "ssh":
                run_example_remote_submit()
                return

            # HTTPS assisted mode
            example_cfg = EXAMPLES[example_dd.value]
            sync_quick_into_widgets()
            cfg_yaml = build_config_from_widgets()

            rd = run_dir(_icesee_run_dir_base(), _new_icesee_run_id())
            dump_yaml(cfg_yaml, rd / "params.yaml")

            # write slurm script locally so user can upload via OnDemand Files
            slurm_text = render_slurm_script({...})  # same as SSH branch
            (rd / "slurm_run.sh").write_text(slurm_text)
            if "{{" in slurm_text or "}}" in slurm_text:
                raise RuntimeError("SLURM_TEMPLATE render left unresolved placeholders. Check keys passed to render_slurm_script().")

            with log_out:
                print("[remote:https] Prepared files in:", rd)
                print(" - params.yaml")
                print(" - slurm_run.sh")
                print("\nNext (OnDemand):")
                print(" 1) Open OnDemand portal:", ood_cluster.value)
                print(" 2) Go to Files -> Home (or project dir) and upload these files")
                print(" 3) Open a Shell and run:")
                print("     sbatch slurm_run.sh")
                print("\nTip: OnDemand access may require GT VPN.")

            set_status("done")
        # submit_btn.on_click(submit_remote)

        def _toggle_auth_widgets(_=None):
            show = (auth_mode.value == "bootstrap")
            cluster_password.layout.display = "block" if show else "none"
            bootstrap_btn.layout.display = "block" if show else "none"

        auth_mode.observe(_toggle_auth_widgets, names="value")
        _toggle_auth_widgets()

        connect_btn.icon = "terminal"
        submit_btn.icon  = "server"
        status_btn.icon  = "tasks"
        tail_btn.icon    = "file-text"

        def _https_url(path_widget: W.Text, run_id: str | None = None, query: dict | None = None) -> str:
            base = https_base.value.strip().rstrip("/")
            path = path_widget.value.strip()
            if not path.startswith("/"):
                path = "/" + path
            url = base + path
            if run_id is not None:
                url = url.rstrip("/") + "/" + run_id
            if query:
                url = url + "?" + urlencode(query)
            return url

        def _extra_headers() -> dict:
            h = {}
            # bearer token
            if https_token.value.strip():
                h["Authorization"] = "Bearer " + https_token.value.strip()
            # yaml headers
            txt = https_headers.value.strip()
            if txt and not txt.startswith("#"):
                try:
                    y = yaml.safe_load(txt) or {}
                    if isinstance(y, dict):
                        h.update({str(k): str(v) for k, v in y.items()})
                except Exception:
                    pass
            return h
        
        def should_use_connector() -> bool:
            mode = access_mode_dd.value

            if mode == "connector":
                return True

            if mode == "direct":
                return False

            # auto mode: use connector only if direct SSH fails
            try:
                result = remote_test_connection(
                    cluster_host.value.strip(),
                    cluster_user.value.strip(),
                    int(cluster_port.value),
                )
                return not result.get("ok", False)
            except Exception:
                return True
    
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
                print("[ssh] Automatic key installation did not complete.")
                print("[ssh] Some clusters require SSH keys to be added through a web portal.")
                print()
                print("[ssh] Copy this public key and add it to the cluster SSH key portal:")
                print()
                print(result.get("public_key_text", "").strip())
                print()
                print("[ssh] After adding the key, return here and click Test SSH.")
                print("[ssh] Then continue using Key-only mode.")

            return result

        def _bootstrap_panel(state, detail=""):
            try:
                remote_conn_panel.set_bootstrap_state(state, detail)
            except (NameError, AttributeError):
                pass

        def on_bootstrap_keys(_=None):
            log_out.clear_output()
            set_status("running")

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)
            password = cluster_password.value

            if not host or not user:
                set_status("fail")
                _bootstrap_panel("connector_failed", "Provide Host + HPC username first.")
                return
            if not password:
                set_status("fail")
                _bootstrap_panel("password_failed", "Enter your HPC password (used once, never stored).")
                return

            bootstrap_btn.disabled = True
            _bootstrap_panel("registering")

            try:
                use_connector = should_use_connector()
                if use_connector:
                    if not SESSION.get("id"):
                        create_or_refresh_connector_session()
                    st = relay_check_status(SESSION["id"], force=True)
                    if not st.get("online"):
                        set_status("fail")
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
                    set_status("done")
                    auth_mode.value = "key"
                    _bootstrap_panel("verifying")
                    with log_out:
                        print("[auth] Public key installed on the resource — verifying access…")
                    try:
                        run_example_remote_test()
                    except Exception as _e:
                        _bootstrap_panel("connector_failed")
                        with log_out:
                            print("[auth] re-check skipped:", type(_e).__name__, _e)
                else:
                    set_status("fail")
                    _bootstrap_panel(verdict)
                    with log_out:
                        print(f"[auth] bootstrap did not complete (reason: "
                              f"{result.get('reason') or verdict}).")

            except Exception as e:
                cluster_password.value = ""
                set_status("fail")
                _bootstrap_panel("timed_out" if "timeout" in type(e).__name__.lower()
                                 else "connector_failed")
                with log_out:
                    print("[auth][ERROR]", type(e).__name__, e)
            finally:
                bootstrap_btn.disabled = False
                cluster_password.value = ""     # never persisted/logged

        # =========================================================
        # Cloud panel widgets (AWS Batch)
        # =========================================================
        aws_region = W.Text(value="us-east-1", layout=W.Layout(width="220px"))
        aws_profile = W.Text(value="", placeholder="(optional) AWS profile", layout=W.Layout(width="220px"))
        cloud_bucket = W.Text(value="", placeholder="s3://bucket/prefix", layout=W.Layout(width="320px"))

        batch_job_queue = W.Text(value="", placeholder="AWS Batch job queue", layout=W.Layout(width="320px"))
        batch_job_def = W.Text(value="", placeholder="job definition (name[:rev])", layout=W.Layout(width="320px"))
        batch_job_name = W.Text(value="icesee", layout=W.Layout(width="220px"))

        cloud_submit_btn = W.Button(description="Submit", icon="cloud-upload", button_style="warning")
        cloud_status_btn = W.Button(description="Check status", icon="search", button_style="")
        cloud_logs_btn = W.Button(description="Logs hint", icon="file-text", button_style="")
        cloud_terminate_btn = W.Button(description="Terminate cloud job", icon="stop", button_style="danger")

        # =========================================================
        # Actions: Local / Remote / Cloud
        # =========================================================
        def run_example_local():
            example_cfg = EXAMPLES[example_dd.value]

            sync_quick_into_widgets()
            cfg = build_config_from_widgets()

            set_status("running")
            log_out.clear_output()

            _run_id = _new_icesee_run_id()

            try:
                result = run_local_example(
                    example_cfg=example_cfg,
                    config=cfg,
                    output_label=output_label_dd.value,
                    generate_report=gen_report.value,
                    run_dir_base=_icesee_run_dir_base(),
                    run_dir_name=_run_id,
                )

                _record_icesee_run(
                    run_dir=result.run_dir, run_id=_run_id, params=cfg,
                    example=example_dd.value, execution_mode="local",
                    backend="local", status="done" if result.success else "failed",
                )
                try:
                    (result.run_dir / "run.log").write_text(result.log_text, encoding="utf-8")
                except Exception:
                    pass   # the Run Log tab falls back to "no local log captured"

                with log_out:
                    print("[local] Example :", example_dd.value)
                    print("[local] Runner  :", RUN_SCRIPT)
                    print("[local] Report  :", REPORT_NB if REPORT_NB else "(none)")
                    print("[local] CWD     :", result.run_dir)
                    print("[local] Command :", " ".join(result.command))
                    print("[local] PYTHONPATH(prepended):", result.external_dir)
                    print("-" * 70)

                    for line in result.log_lines:
                        print(line)

                    print("-" * 70)
                    print("Return code:", result.returncode)

                    if result.report_notebook is not None:
                        print("[local] Report done.")

                if not result.success:
                    set_status("fail")
                    refresh_results_preview(result.run_dir, results_out)
                    return

                set_status("done")
                refresh_results_preview(result.run_dir, results_out)

                if open_latest.value:
                    with log_out:
                        print("\nRun folder:", result.run_dir)

            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[local][ERROR]", type(e).__name__, e)

        def run_example_remote_submit():
            log_out.clear_output()
            set_status("running")

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            with log_out:
                print("[remote] Submit job")
                print("  host:", host)
                print("  user:", user)
                print("  port:", port)
                print("  example:", example_dd.value)
                print("-" * 70)

            try:

                use_connector = access_mode_dd.value == "connector"

                if access_mode_dd.value == "auto":
                    direct = remote_test_connection(host, user, port)
                    use_connector = not direct.get("ok", False)

                if use_connector:
                    if not SESSION.get("id"):
                        create_or_refresh_connector_session()

                    st = relay_check_status(SESSION["id"], force=True)
                    if not st.get("online"):
                        set_status("fail")
                        with log_out:
                            print("[connector][ERROR] Connector session is not online.")
                        return

                # B3: remote-access identity gate -- verify the real remote
                # identity vs the configured HPC username; block Run on mismatch.
                _resolved = "connector" if use_connector else "direct"
                _gate = enforce_remote_access(
                    RemoteBridge(
                        mode=_resolved, host=host, user=user, port=port,
                        session_id=SESSION.get("id"),
                        cluster_name=cluster_name_for_keys.value or "pace",
                    ),
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
                    set_status("fail")
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
                    set_status("fail")
                    with log_out:
                        print("[slurm][ERROR] Fix the job resource request:")
                        for _m in _slurm_errors:
                            print("  -", _m)
                    return

                example_cfg = EXAMPLES[example_dd.value]

                sync_quick_into_widgets()
                cfg_yaml = build_config_from_widgets()
                params_text = yaml.safe_dump(cfg_yaml, sort_keys=False)

                _run_id = _new_icesee_run_id()
                _rd = run_dir(_icesee_run_dir_base(), _run_id)

                if exec_backend_choice.value == "spack":
                    if use_connector:
                        result = submit_remote_example_via_connector(
                            session_id=SESSION["id"],
                            host=host,
                            user=user,
                            port=port,
                            example_cfg=example_cfg,
                            params_text=params_text,
                            remote_base_dir=remote_base_dir.value,
                            remote_tag=remote_tag.value,
                            spack_enable=spack_enable.value,
                            spack_repo_url=spack_repo_url.value,
                            spack_dirname=spack_dirname.value,
                            spack_install_if_needed=spack_install_if_needed.value,
                            spack_install_mode=spack_install_mode.value,
                            spack_slurm_dir=spack_slurm_dir.value,
                            spack_pmix_dir=spack_pmix_dir.value,
                            spack_use_existing_sbatch=spack_use_existing_sbatch.value,
                            slurm_time=slurm_time.value,
                            slurm_job_name=slurm_job_name.value,
                            slurm_nodes=slurm_nodes.value,
                            slurm_ntasks=slurm_ntasks.value,
                            slurm_tpn=slurm_tpn.value,
                            slurm_part=slurm_part.value,
                            slurm_mem=slurm_mem.value,
                            slurm_account=slurm_account.value,
                            slurm_mail=slurm_mail.value,
                            remote_module_lines=remote_module_lines.value,
                            remote_export_lines=remote_export_lines.value,
                            cluster_mpi_np=cluster_mpi_np.value,
                            ens_size=ens_sl.value,
                            cluster_model_nprocs=cluster_model_nprocs.value,
                            cluster_name=cluster_name_for_keys.value,
                        )
                    else:
                        result = submit_remote_example(
                        host=host,
                        user=user,
                        port=port,
                        example_cfg=example_cfg,
                        params_text=params_text,
                        remote_base_dir=remote_base_dir.value,
                        remote_tag=remote_tag.value,
                        spack_enable=spack_enable.value,
                        spack_repo_url=spack_repo_url.value,
                        spack_dirname=spack_dirname.value,
                        spack_install_if_needed=spack_install_if_needed.value,
                        spack_install_mode=spack_install_mode.value,
                        spack_slurm_dir=spack_slurm_dir.value,
                        spack_pmix_dir=spack_pmix_dir.value,
                        spack_use_existing_sbatch=spack_use_existing_sbatch.value,
                        slurm_time=slurm_time.value,
                        slurm_job_name=slurm_job_name.value,
                        slurm_nodes=slurm_nodes.value,
                        slurm_ntasks=slurm_ntasks.value,
                        slurm_tpn=slurm_tpn.value,
                        slurm_part=slurm_part.value,
                        slurm_mem=slurm_mem.value,
                        slurm_account=slurm_account.value,
                        slurm_mail=slurm_mail.value,
                        remote_module_lines=remote_module_lines.value,
                        remote_export_lines=remote_export_lines.value,
                        cluster_mpi_np=cluster_mpi_np.value,
                        ens_size=ens_sl.value,
                        cluster_model_nprocs=cluster_model_nprocs.value,
                    )
                else:
                    if use_connector:
                        result = submit_remote_example_container_via_connector(
                            session_id=SESSION["id"],
                            host=host,
                            user=user,
                            port=port,
                            example_cfg=example_cfg,
                            params_text=params_text,
                            remote_base_dir=remote_base_dir.value,
                            remote_tag=remote_tag.value,
                            spack_repo_url=spack_repo_url.value,
                            spack_dirname=spack_dirname.value,
                            slurm_time=slurm_time.value,
                            slurm_job_name=slurm_job_name.value,
                            slurm_nodes=slurm_nodes.value,
                            slurm_ntasks=slurm_ntasks.value,
                            slurm_tpn=slurm_tpn.value,
                            slurm_part=slurm_part.value,
                            slurm_mem=slurm_mem.value,
                            slurm_account=slurm_account.value,
                            slurm_mail=slurm_mail.value,
                            remote_module_lines=remote_module_lines.value,
                            remote_export_lines=remote_export_lines.value,
                            cluster_mpi_np=cluster_mpi_np.value,
                            ens_size=ens_sl.value,
                            cluster_model_nprocs=cluster_model_nprocs.value,
                            container_source=container_source.value,
                            container_image_uri=container_image_uri.value,
                            cluster_name=cluster_name_for_keys.value,
                        )
                    else:
                        result = submit_remote_example_container(
                            host=host,
                            user=user,
                            port=port,
                            example_cfg=example_cfg,
                            params_text=params_text,
                            remote_base_dir=remote_base_dir.value,
                            remote_tag=remote_tag.value,
                            spack_repo_url=spack_repo_url.value,
                            spack_dirname=spack_dirname.value,
                            slurm_time=slurm_time.value,
                            slurm_job_name=slurm_job_name.value,
                            slurm_nodes=slurm_nodes.value,
                            slurm_ntasks=slurm_ntasks.value,
                            slurm_tpn=slurm_tpn.value,
                            slurm_part=slurm_part.value,
                            slurm_mem=slurm_mem.value,
                            slurm_account=slurm_account.value,
                            slurm_mail=slurm_mail.value,
                            remote_module_lines=remote_module_lines.value,
                            remote_export_lines=remote_export_lines.value,
                            cluster_mpi_np=cluster_mpi_np.value,
                            ens_size=ens_sl.value,
                            cluster_model_nprocs=cluster_model_nprocs.value,
                            container_source=container_source.value,
                            container_image_uri=container_image_uri.value,
                        )

                STATUS["remote_dir"] = result.remote_dir
                STATUS["jobid"] = result.jobid
                STATUS["local_run_dir"] = str(_rd)

                _record_icesee_run(
                    run_dir=_rd, run_id=_run_id, params=cfg_yaml,
                    example=example_dd.value, execution_mode="remote",
                    backend=exec_backend_choice.value,
                    source=example_dd.value,
                    run_target=cluster_name_for_keys.value or host,
                    status="running", jobid=result.jobid,
                    remote_directory=result.remote_dir,
                )

                experiment_bridge.create(
                    application="icesee",

                    name=(
                        f"ICESEE "
                        f"{filter_alg_dd.value} run"
                    ),

                    backend=remote_backend.value,

                    status="running",

                    job_id=(
                        str(result.jobid)
                        if result.jobid is not None
                        else None
                    ),

                    cluster=(
                        cluster_name_for_keys.value
                        or cluster_host.value.strip()
                    ),

                    working_directory=result.remote_dir,

                    log_path=getattr(
                        result,
                        "log_file",
                        None,
                    ),

                    configuration=(
                        current_experiment_configuration()
                    ),

                    metadata={
                        "execution_mode": "remote",
                        "access_mode": (
                            access_mode_dd.value
                        ),
                        "backend": (
                            remote_backend.value
                        ),
                        "filter": (
                            filter_alg_dd.value
                        ),
                        "preset": (
                            preset_dd.value
                        ),
                        "example": (
                            example_dd.value
                        ),
                    },
                )

                workspace_bridge.save(
                    application="icesee",
                    state=current_workspace_state(),
                )

                set_status("done")

                with log_out:
                    print(
                        "[experiment] Tracking ICESEE "
                        f"{filter_alg_dd.value} run "
                        f"for job {result.jobid}"
                    )

                    for msg in result.messages:
                        print(msg)

            except subprocess.TimeoutExpired:
                set_status("fail")
                with log_out:
                    print("[remote][TIMEOUT] SSH/Sbatch step timed out.")
            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def run_example_remote_test():
            log_out.clear_output()
            set_status("running")
            try:
                remote_conn_panel.set_status("checking")
            except NameError:
                pass

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            with log_out:
                print("[remote] Test SSH")
                print("  host:", host)
                print("  user:", user)
                print("  port:", port)
                print("  cmd : hostname && whoami && date")
                print("-" * 70)

            if not host or not user:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR] Provide Host + User first.")
                return

            def _report_identity(resolved_mode: str, precheck_stdout: str = "") -> None:
                try:
                    _vcmd = get_compute_profile(
                        cluster_name_for_keys.value or "pace").verification_command
                    # The Test SSH probe just ran `hostname && whoami && pwd &&
                    # date`. When identity is just `whoami`, reuse that instead
                    # of a second remote round trip. (The Run gate re-verifies
                    # fresh regardless.)
                    _lines = [ln.strip() for ln in (precheck_stdout or "").splitlines() if ln.strip()]
                    if len(_lines) >= 2 and can_reuse_connectivity_identity(_vcmd):
                        _v = identity_result_from_output(
                            whoami_line=_lines[1], expected_username=user
                        )
                    else:
                        _v = verify_remote_identity(
                            RemoteBridge(mode=resolved_mode, host=host, user=user, port=port,
                                         session_id=SESSION.get("id"),
                                         cluster_name=cluster_name_for_keys.value or "pace"),
                            verification_command=_vcmd,
                            expected_username=user,
                        )
                    with log_out:
                        if _v.ok:
                            print(f"[identity] verified — remote '{_v.remote_identity}' "
                                  "matches the configured HPC username.")
                        elif _v.mismatch:
                            print(f"[identity][MISMATCH] remote '{_v.remote_identity}' != "
                                  f"configured '{_v.expected}'. Run is blocked until this matches.")
                        else:
                            print(f"[identity] could not verify remote identity: {_v.error}")
                    try:
                        remote_conn_panel.set_status(
                            "verified" if _v.ok else "mismatch" if _v.mismatch else "failed"
                        )
                    except NameError:
                        pass
                except Exception as _e:
                    with log_out:
                        print("[identity] verification skipped:", type(_e).__name__, _e)
                    try:
                        remote_conn_panel.set_status("failed")
                    except NameError:
                        pass

            def _classify_and_report_failure(res) -> None:
                """A failed connectivity probe: a public-key rejection is an
                actionable "register your CryoStack key" state (B3 namespaced
                key), everything else stays a generic failure."""
                _kind = classify_ssh_failure(
                    stderr=(res or {}).get("stderr", ""),
                    stdout=(res or {}).get("stdout", ""),
                    returncode=(res or {}).get("returncode"),
                )
                try:
                    _profile = get_compute_profile(cluster_name_for_keys.value or "pace")
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

            try:

                if access_mode_dd.value == "connector":
                    if not SESSION.get("id"):
                        create_or_refresh_connector_session()

                    st = relay_check_status(SESSION["id"])
                    if not st.get("online"):
                        set_status("fail")
                        with log_out:
                            print("[connector][ERROR] Connector session is not online.")
                            print("Open the connector setup page and start the local connector first.")
                        return

                    cluster_name = cluster_name_for_keys.value or "pace"
                    payload = connector_ssh(
                        SESSION["id"],
                        host,
                        user,
                        port,
                        "hostname && whoami && pwd && date",
                        timeout=300,
                        cluster_name=cluster_name,
                    )

                    with log_out:
                        print("[connector] Test SSH via local connector / VPN bridge")
                        print("ok:", payload.get("ok"))
                        print("returncode:", payload.get("returncode"))
                        if (payload.get("stdout") or "").strip():
                            print("--- stdout ---")
                            print(payload["stdout"].strip())
                        if (payload.get("stderr") or "").strip():
                            print("--- stderr ---")
                            print(payload["stderr"].strip())

                    if payload.get("ok"):
                        _report_identity("connector", payload.get("stdout") or "")
                        set_status("done")
                    else:
                        set_status("fail")
                        _classify_and_report_failure(payload)
                    return
                result = remote_test_connection(host, user, port)

                with log_out:
                    print("returncode:", result["returncode"])

                    if (result["stdout"] or "").strip():
                        print("--- stdout ---")
                        print(result["stdout"].strip())

                    if (result["stderr"] or "").strip():
                        print("--- stderr ---")
                        print(result["stderr"].strip())

                    if result["returncode"] != 0:
                        err = (result["stderr"] or "").lower()

                        if "permission denied" in err:
                            print()
                            print("⚠ SSH authentication failed.")
                            print("Looks like passwordless SSH is not configured.")
                            print()
                            print("➡ Fix:")
                            print("   1) Switch Auth → 'Bootstrap with password'")
                            print("   2) Enter your cluster password")
                            print("   3) Click 'Enable passwordless SSH'")
                            print()
                            print("After that the UI will connect automatically.")

                        elif "timed out" in err or "connection timed out" in err:
                            print()
                            print("⚠ Connection timed out.")
                            print("Check VPN, firewall, or hostname.")

                        elif "could not resolve hostname" in err:
                            print()
                            print("⚠ Hostname not reachable.")
                            print("Check the cluster hostname.")

                if result["ok"]:
                    _report_identity("direct", result.get("stdout") or "")
                    set_status("done")
                else:
                    set_status("fail")
                    _classify_and_report_failure(result)

            except subprocess.TimeoutExpired:
                set_status("fail")
                with log_out:
                    print("[remote][TIMEOUT] SSH did not respond within 15s.")
                    print("Likely: network/DNS issue, firewall/VPN, or auth prompt prevented non-interactive login.")
            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def run_example_remote_status():
            log_out.clear_output()
            set_status("running")

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            jobid = STATUS.get("jobid")

            with log_out:
                print("[remote] Check status")
                print("  host:", host)
                print("  user:", user)
                print("  jobid:", jobid)
                print("-" * 70)

            if not jobid:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR] No JobID yet. Submit first.")
                return

            try:
                result = remote_job_status(
                    host,
                    user,
                    port,
                    jobid,
                )

                experiment_update = (
                    experiment_update_from_job_status(
                        result
                    )
                )

                if experiment_update:
                    experiment_bridge.update_by_job(
                        job_id=str(jobid),
                        **experiment_update,
                    )
                    if STATUS.get("local_run_dir"):
                        _update_icesee_run(
                            Path(STATUS["local_run_dir"]),
                            status=experiment_update.get("status"),
                        )

                with log_out:
                    if result["source"] == "squeue":
                        print("--- squeue ---")
                        print(
                            (result["stdout"] or "").strip()
                        )
                    else:
                        print(
                            "(squeue empty; job likely "
                            "finished or left the queue)"
                        )
                        print("--- sacct ---")
                        print(
                            (result["stdout"] or "").strip()
                            or "(no sacct output)"
                        )

                        if (
                            result["stderr"] or ""
                        ).strip():
                            print("--- stderr ---")
                            print(
                                result["stderr"].strip()
                            )

                    if experiment_update:
                        print()
                        print(
                            "[experiment] CryoStack status:",
                            experiment_update["status"],
                        )

                set_status(
                    "done"
                    if result["returncode"] == 0
                    else "fail"
                )

            except subprocess.TimeoutExpired:
                set_status("fail")
                with log_out:
                    print("[remote][TIMEOUT] Status check timed out.")
            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def run_example_remote_cancel():
            log_out.clear_output()
            set_status("running")

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            jobid = STATUS.get("jobid")

            with log_out:
                print("[remote] Cancel job")
                print("  host:", host)
                print("  user:", user)
                print("  jobid:", jobid)
                print("-" * 70)

            if not jobid:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR] No JobID found.")
                return

            try:
                result = remote_cancel_job(host, user, port, jobid)

                with log_out:
                    print("returncode:", result["returncode"])

                    if (result["stdout"] or "").strip():
                        print("--- stdout ---")
                        print(result["stdout"].strip())

                    if (result["stderr"] or "").strip():
                        print("--- stderr ---")
                        print(result["stderr"].strip())

                    if result["ok"]:
                        print(f"✅ Job {jobid} cancelled.")

                set_status("done" if result["ok"] else "fail")

            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def run_example_remote_tail():
            log_out.clear_output()
            set_status("running")

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            rdir = STATUS.get("remote_dir")
            jobid = STATUS.get("jobid")

            with log_out:
                print("[remote] Tail log")
                print("  host:", host)
                print("  user:", user)
                print("  rdir:", rdir)
                print("  jobid:", jobid)
                print("-" * 70)

            if not rdir or not jobid:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR] No remote dir / JobID. Submit first.")
                return

            try:
                result = remote_tail_log(host, user, port, rdir, jobid, n=120)

                with log_out:
                    print("[remote] file:", result["log_file"])
                    print("--- tail ---")
                    print((result["stdout"] or "").rstrip())
                    if (result["stderr"] or "").strip():
                        print("--- stderr ---")
                        print(result["stderr"].strip())

                set_status("done" if result["returncode"] == 0 else "fail")

            except subprocess.TimeoutExpired:
                set_status("fail")
                with log_out:
                    print("[remote][TIMEOUT] Tail timed out.")
            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def _icesee_cloud_bridge_config() -> IceseeCloudBridgeConfig:
            """Fresh per-operation bridge config from the live Cloud widgets
            -- the same 'temporary-role refresh per lifecycle operation'
            pattern CryoLauncher's own current_cloud_bridge() uses, rather
            than caching one bridge across the session."""
            return IceseeCloudBridgeConfig(
                region=aws_region.value.strip() or "us-east-1",
                profile=(aws_profile.value.strip() or None),
            )

        def run_example_cloud_submit():
            example_cfg = EXAMPLES[example_dd.value]

            sync_quick_into_widgets()
            cfg_yaml = build_config_from_widgets()

            set_status("running")
            log_out.clear_output()
            with log_out:
                print("[cloud] AWS Batch submit")
                print("example:", example_dd.value)
                print("region :", aws_region.value.strip() or "us-east-1")
                print("profile:", aws_profile.value.strip() or "(default)")
                print("s3     :", cloud_bucket.value.strip())

            _run_id = _new_icesee_run_id()
            _rd = run_dir(_icesee_run_dir_base(), _run_id)

            try:
                bridge = build_icesee_cloud_bridge(_icesee_cloud_bridge_config())
                result = submit_icesee_cloud_run(
                    bridge,
                    example_name=example_dd.value,
                    example_cfg=example_cfg,
                    config=cfg_yaml,
                    s3_prefix=cloud_bucket.value.strip(),
                    job_queue=batch_job_queue.value.strip(),
                    job_definition=batch_job_def.value.strip(),
                    job_name=(batch_job_name.value.strip() or "icesee"),
                    run_dir_base=_icesee_run_dir_base(),
                    run_dir_name=_run_id,
                )

                STATUS["batch_job_id"] = result.job_id
                STATUS["s3_run"] = result.working_directory
                STATUS["local_run_dir"] = str(_rd)

                _record_icesee_run(
                    run_dir=_rd, run_id=_run_id,
                    params=cfg_yaml, example=example_dd.value,
                    execution_mode="cloud", backend="aws",
                    source=example_dd.value,
                    run_target=batch_job_def.value.strip(),
                    status="running", jobid=result.job_id,
                    remote_directory=result.working_directory,
                )
                _merge_icesee_aws_resources(_rd, {
                    "region": aws_region.value.strip() or "us-east-1",
                    "batch_job_id": result.job_id,
                    "job_queue": batch_job_queue.value.strip(),
                    "job_definition": batch_job_def.value.strip(),
                    "s3_run": result.working_directory,
                })

                set_status("done")
                with log_out:
                    for msg in result.messages:
                        print(msg)

            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[cloud][ERROR]", type(e).__name__, e)

        def run_example_cloud_status():
            if not STATUS.get("batch_job_id"):
                with log_out:
                    print("[cloud] No Batch job id yet. Submit first.")
                return
            try:
                bridge = build_icesee_cloud_bridge(_icesee_cloud_bridge_config())
                st = icesee_cloud_status(bridge, job_id=STATUS["batch_job_id"])
                with log_out:
                    print("[cloud] status:", st.raw_state)
                    if st.reason:
                        print("[cloud] reason:", st.reason)
                if STATUS.get("local_run_dir"):
                    _update_icesee_run(Path(STATUS["local_run_dir"]), status=st.state)
                    _merge_icesee_aws_resources(
                        Path(STATUS["local_run_dir"]), resources_from_poll(st.metadata),
                    )
            except Exception as e:
                with log_out:
                    print("[cloud][ERROR]", type(e).__name__, e)

        def run_example_cloud_terminate():
            if not STATUS.get("batch_job_id"):
                with log_out:
                    print("[cloud] No Batch job id yet.")
                return
            try:
                bridge = build_icesee_cloud_bridge(_icesee_cloud_bridge_config())
                result = icesee_cloud_terminate(bridge, job_id=STATUS["batch_job_id"])
                with log_out:
                    print("[cloud]", result.get("message")
                          or f"job {result.get('action', 'terminated')}")
                if STATUS.get("local_run_dir"):
                    _update_icesee_run(Path(STATUS["local_run_dir"]), status="cancelled")
            except Exception as e:
                with log_out:
                    print("[cloud][ERROR]", type(e).__name__, e)

        def run_example_cloud_logs_hint():
            if not STATUS.get("batch_job_id"):
                with log_out:
                    print("[cloud] No Batch job id yet.")
                return
            with log_out:
                print("[cloud] Logs depend on your job definition (awslogs driver).")
                print("Open the AWS Console -> Batch -> Job -> Logs")
                print("JobID:", STATUS["batch_job_id"])
                if STATUS.get("s3_run"):
                    print("S3 run prefix:", STATUS["s3_run"])

        def current_execution_mode() -> str:
            """
            Return the active ICESEE execution mode.

            mode_tabs:
                0 -> Local
                1 -> Remote
                2 -> Cloud
            """
            index = mode_tabs.selected_index

            return {
                0: "local",
                1: "remote",
                2: "cloud",
            }.get(index, "local")


        def current_experiment_configuration() -> dict:
            """
            Snapshot the scientific and execution configuration used
            for an ICESEE experiment.

            Do not store passwords, SSH keys, connector secrets,
            AWS credentials, or other authentication material.
            """

            execution_mode = current_execution_mode()

            config = {
                "execution_mode": execution_mode,

                "example": example_dd.value or "",

                "preset": preset_dd.value or "",

                "filter": filter_alg_dd.value or "",

                "ensemble_size": int(ens_sl.value),

                "output": output_label_dd.value or "",

                "report_generation": bool(
                    gen_report.value
                ),
            }

            # -------------------------------------------------
            # Remote / HPC configuration
            # -------------------------------------------------
            if execution_mode == "remote":

                config["remote"] = {
                    "access_mode": (
                        access_mode_dd.value
                    ),

                    "backend": (
                        remote_backend.value
                    ),

                    "cluster": (
                        cluster_name_for_keys.value
                        if "cluster_name_for_keys" in locals()
                        else ""
                    ),

                    "host": (
                        cluster_host.value.strip()
                    ),

                    "port": int(
                        cluster_port.value
                    ),

                    "remote_base_dir": (
                        remote_base_dir.value.strip()
                    ),

                    "remote_tag": (
                        remote_tag.value.strip()
                    ),
                }

                config["slurm"] = {
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

                    "account": (
                        slurm_account.value
                    ),
                }

            # -------------------------------------------------
            # Cloud configuration
            # -------------------------------------------------
            elif execution_mode == "cloud":

                config["cloud"] = {
                    "region": (
                        aws_region.value.strip()
                    ),

                    "job_queue": (
                        batch_job_queue.value.strip()
                    ),

                    "job_definition": (
                        batch_job_def.value.strip()
                    ),

                    "job_name": (
                        batch_job_name.value.strip()
                    ),

                    "s3_prefix": (
                        cloud_bucket.value.strip()
                    ),
                }

            return config


        def current_workspace_state() -> dict:
            """
            Save enough ICESEE UI state to support future workspace
            restoration.

            This intentionally excludes credentials and secrets.
            """

            execution_mode = current_execution_mode()

            state = {
                "execution_mode": execution_mode,

                "example": example_dd.value or "",

                "preset": preset_dd.value or "",

                "filter": filter_alg_dd.value or "",

                "ensemble_size": int(ens_sl.value),

                "output": output_label_dd.value or "",

                "report_generation": bool(
                    gen_report.value
                ),

                "job": {
                    "job_id": (
                        STATUS.get("jobid")
                    ),

                    "remote_directory": (
                        STATUS.get("remote_dir")
                    ),

                    "batch_job_id": (
                        STATUS.get("batch_job_id")
                    ),

                    "s3_run": (
                        STATUS.get("s3_run")
                    ),
                },
            }

            # -------------------------------------------------
            # Remote workspace
            # -------------------------------------------------
            if execution_mode == "remote":

                state["remote"] = {
                    "access_mode": (
                        access_mode_dd.value
                    ),

                    "backend": (
                        remote_backend.value
                    ),

                    "cluster": (
                        cluster_name_for_keys.value
                        if "cluster_name_for_keys" in locals()
                        else ""
                    ),

                    "host": (
                        cluster_host.value.strip()
                    ),

                    "port": int(
                        cluster_port.value
                    ),

                    "remote_base_dir": (
                        remote_base_dir.value.strip()
                    ),

                    "remote_tag": (
                        remote_tag.value.strip()
                    ),
                }

                state["slurm"] = {
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
                }

            # -------------------------------------------------
            # Cloud workspace
            # -------------------------------------------------
            elif execution_mode == "cloud":

                state["cloud"] = {
                    "region": (
                        aws_region.value.strip()
                    ),

                    "job_queue": (
                        batch_job_queue.value.strip()
                    ),

                    "job_definition": (
                        batch_job_def.value.strip()
                    ),

                    "job_name": (
                        batch_job_name.value.strip()
                    ),

                    "s3_prefix": (
                        cloud_bucket.value.strip()
                    ),
                }

            # B2: fold in the authenticated user x resource personal settings
            # (v2 shape). RESOURCE facts are NOT persisted; nothing secret.
            merged = resource_state.capture()
            merged["run"] = state
            return strip_secrets(merged)

        # master run
        def run_example():
            mode = get_mode()
            if mode == MODE_REMOTE:
                return run_example_remote_submit()
            if mode == MODE_CLOUD:
                return run_example_cloud_submit()
            return run_example_local()

        # =========================================================
        # Wire buttons
        # =========================================================
        # run_btn.on_click(lambda b: run_example())
        action_btn.on_click(on_action_click)
        clear_btn.on_click(lambda b: (log_out.clear_output(), results_out.clear_output(), set_status("idle")))

        def _on_check_ssh(_b=None):
            # immediate feedback + no re-entry while the check runs
            connect_btn.disabled = True
            try:
                remote_conn_panel.set_status("checking")
            except NameError:
                pass
            try:
                run_example_remote_test()
            finally:
                connect_btn.disabled = False

        connect_btn.on_click(_on_check_ssh)
        submit_btn.on_click(lambda b: run_example_remote_submit())
        status_btn.on_click(lambda b: run_example_remote_status())
        tail_btn.on_click(lambda b: run_example_remote_tail())
        terminate_btn.on_click(lambda b: run_example_remote_cancel())

        cloud_submit_btn.on_click(lambda b: run_example_cloud_submit())
        cloud_status_btn.on_click(lambda b: run_example_cloud_status())
        cloud_logs_btn.on_click(lambda b: run_example_cloud_logs_hint())
        cloud_terminate_btn.on_click(lambda b: run_example_cloud_terminate())
        
        start_connector_session_btn.on_click(create_or_refresh_connector_session)
        # (removed: auto connector-session creation on access-mode change --
        #  the session is created lazily at Check SSH / Run / the explicit
        #  "Open Connector Setup" button, keeping the relay off the
        #  initial-load and resource-switch paths.)
        preview_results_btn.on_click(preview_remote_results)
        results_download_btn.on_click(download_results_bundle)

        # keep template in sync with quick knobs
        def _sync_knobs(_=None):
            sync_quick_into_widgets()

        filter_alg_dd.observe(_sync_knobs, names="value")
        ens_sl.observe(_sync_knobs, names="value")
        seed_in.observe(_sync_knobs, names="value")

        bootstrap_btn.on_click(on_bootstrap_keys)

    # =========================================================
        # UX CSS
        # =========================================================
        css = """
        <style>
        /* --- your existing styles --- */
        .icesee-wrap { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; }
        .icesee-title { font-size: 18px; font-weight: 700; margin: 6px 0 4px; }
        .icesee-subtitle { color: rgba(0,0,0,.65); margin-bottom: 14px; }
        .icesee-card { border: 1px solid rgba(0,0,0,.10); border-radius: 12px; padding: 14px; background: #fff; }
        .icesee-h { font-size: 18px; font-weight: 800; margin: 2px 0 10px; }
        .icesee-lbl { min-width: 80px; font-weight: 650; }
        .icesee-lbl-wide { min-width: 120px; font-weight: 650; }
        .icesee-lbl-sm { min-width: 56px; font-weight: 650; }
        .icesee-k { min-width: 180px; font-weight: 650; color: rgba(0,0,0,.78); }
        .icesee-subtle { color: rgba(0,0,0,.60); font-size: 12px; }
        .icesee-status { display:inline-block; padding: 8px 14px; border-radius: 999px; font-weight: 700; border: 1px solid rgba(0,0,0,.10); }
        .icesee-idle { background: rgba(0,0,0,.04); }
        .icesee-running { background: rgba(16, 122, 255, .12); }
        .icesee-done { background: rgba(30, 170, 80, .14); }
        .icesee-fail { background: rgba(220, 60, 60, .14); }

        /* --- make notebook/page use full width (JLab/classic) --- */
        .jp-NotebookPanel, .jp-Notebook, .jp-Cell, .jp-OutputArea { max-width: 100% !important; }
        .icesee-page { width: 100% !important; }

        /* --- stretch left/right columns properly --- */
        .icesee-row { display: flex; gap: 26px; width: 100%; align-items: stretch; }
        .icesee-col { flex: 1 1 0; min-width: 0; }  /* min-width:0 is KEY */

        /* --- outputs: full width + readable long lines --- */
        .icesee-out { width: 100% !important; }
        .icesee-out .output_area pre {
        white-space: pre;      /* keep formatting */
        overflow-x: auto;      /* horizontal scroll for long lines */
        }

        /* Optional: if you're in Jupyter Book and it's still constrained, uncomment:
        .bd-main .bd-content, .bd-container, .container-xl, .container-lg { max-width: 100% !important; }
        */
        </style>
        """
        # display(W.HTML(css))
        display(shared_styles)

        # =========================================================
        # Layout
        # =========================================================
        header = W.HTML(
            "<div class='icesee-wrap'>"
            "<div class='icesee-title'>Ice-Sheet Modeling with Data Assimilation</div>"
            "<div class='icesee-subtitle'>Outputs and reports are saved and previewed on the right.</div>"
            "</div>"
        )

        # Local tab content
        local_tab_card = W.VBox([W.HTML("<div class='icesee-subtle'>Local mode runs directly in this notebook.</div>")])
        local_tab_card.add_class("icesee-card")

        ssh_key_manager = build_ssh_key_manager(
            cluster_name_widget=cluster_name_for_keys,
            host_widget=cluster_host,
            user_widget=cluster_user,
            defer_probe=True,   # ssh-add subprocesses off the construction path
            )
        exec_backend_row = W.HBox(
            [W.HTML("<div class='icesee-lbl'>Exec backend:</div>"), exec_backend_choice],
            layout=W.Layout(gap="12px"),
        )

        container_source_row = W.HBox(
            [W.HTML("<div class='icesee-lbl'>Source:</div>"), container_source],
            layout=W.Layout(gap="12px"),
        )

        container_image_row = W.HBox(
            [W.HTML("<div class='icesee-lbl'>Image:</div>"), container_image_uri],
            layout=W.Layout(gap="12px"),
        )
        

        def _toggle_exec_backend_ui(_=None):
            is_container = (exec_backend_choice.value == "container")

            container_source_row.layout.display = "flex" if is_container else "none"
            container_image_row.layout.display = "flex" if is_container else "none"

            spack_display = "none" if is_container else "flex"
            spack_block_display = "none" if is_container else "block"

            spack_section_title.layout.display = spack_block_display
            spack_enable_row.layout.display = spack_block_display
            spack_repo_row.layout.display = spack_display
            spack_dir_row.layout.display = spack_display
            spack_install_if_needed_row.layout.display = spack_block_display
            spack_install_mode_row.layout.display = spack_display
            spack_slurm_dir_row.layout.display = spack_display
            spack_pmix_dir_row.layout.display = spack_display
            spack_existing_sbatch_row.layout.display = spack_block_display

            if is_container:
                spack_enable.value = False

        spack_section_title = W.HTML("<div class='icesee-subtle' style='margin-top:10px'>ICESEE-Spack</div>")
        spack_enable_row = W.Box([spack_enable], layout=W.Layout(margin="0 0 0 120px"))
        spack_repo_row = W.HBox([W.HTML("<div class='icesee-lbl'>Repo:</div>"), spack_repo_url], layout=W.Layout(gap="12px"))
        spack_dir_row = W.HBox([W.HTML("<div class='icesee-lbl'>Dir name:</div>"), spack_dirname], layout=W.Layout(gap="12px"))
        spack_install_if_needed_row = W.Box([spack_install_if_needed], layout=W.Layout(margin="0 0 0 120px"))
        spack_install_mode_row = W.HBox([W.HTML("<div class='icesee-lbl'>Install:</div>"), spack_install_mode], layout=W.Layout(gap="12px"))
        spack_slurm_dir_row = W.HBox([W.HTML("<div class='icesee-lbl'>SLURM_DIR:</div>"), spack_slurm_dir], layout=W.Layout(gap="12px"))
        spack_pmix_dir_row = W.HBox([W.HTML("<div class='icesee-lbl'>PMIX_DIR:</div>"), spack_pmix_dir], layout=W.Layout(gap="12px"))
        spack_existing_sbatch_row = W.Box([spack_use_existing_sbatch], layout=W.Layout(margin="0 0 0 120px"))

        # B4: Job settings / Compute resources / Allocation are arranged by
        # build_slurm_resources_panel; only ICESEE's MPI + module/export rows
        # are laid out here and handed to the panel as extra_children.
        mpi_model_row = W.HBox(
            [form_pair("MPI np:", cluster_mpi_np), form_pair("Model nprocs:", cluster_model_nprocs, label_width="120px")],
            layout=W.Layout(gap="8px", width="100%"),
        )

        modules_title = W.HTML("<div class='icesee-subtle' style='margin-top:10px'>Modules</div>")
        exports_title = W.HTML("<div class='icesee-subtle' style='margin-top:10px'>Exports</div>")
        ssh_key_title = W.HTML("<div class='icesee-subtle' style='margin-top:12px;'>SSH key manager</div>")

        download_buttons_row = W.HBox(
            [preview_results_btn, results_download_btn],
            layout=W.Layout(
                gap="10px",
                justify_content="flex-end",
                align_items="center",
                width="100%",
                margin="10px 0 0 0",
            ),
        )


        # B4: user-workflow-oriented Remote Connection panel (Compute resource /
        # Your HPC identity / Access / Status), connector + session internals
        # behind Diagnostics. Transport, B3 AccessState, identity verification
        # and the Run gate are unchanged.
        connect_btn.description = "Check SSH Access"
        start_connector_session_btn.description = "Open Connector Setup"
        start_connector_session_btn.icon = "external-link"

        remote_tag_row = form_pair("Tag:", remote_tag, label_width="56px")
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
        remote_conn_inner = remote_conn_panel.container


        exec_backend_inner = W.VBox([
            exec_backend_row,
            container_source_row,
            container_image_row,
            spack_enable_row,
            spack_repo_row,
            spack_dir_row,
            spack_install_if_needed_row,
            spack_install_mode_row,
            spack_slurm_dir_row,
            spack_pmix_dir_row,
            spack_existing_sbatch_row,
        ], layout=W.Layout(gap="8px"))


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
            extra_children=[
                mpi_model_row,
                modules_title,
                remote_module_lines,
                exports_title,
                remote_export_lines,
            ],
        ).container

        remote_conn_box = W.Accordion(children=[remote_conn_inner])
        remote_conn_box.set_title(0, "🔌 Remote connection")
        remote_conn_box.selected_index = None

        exec_backend_box = W.Accordion(children=[exec_backend_inner])
        exec_backend_box.set_title(0, "⚙️ Execution backend")
        exec_backend_box.selected_index = None

        slurm_box = W.Accordion(children=[slurm_inner])
        slurm_box.set_title(0, "📊 Slurm resources")
        slurm_box.selected_index = None

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

        def _probe_ssh_key_manager(change):
            if change.get("new") is not None:
                probe = getattr(ssh_key_manager, "_cryostack_probe", None)
                if probe is not None:
                    probe()
        ssh_key_manager_box.observe(_probe_ssh_key_manager, names="selected_index")

        # =========================================================
        # Workspace (Runs / Files) -- the same structural language as
        # CryoLauncher's Workspace shell, reusing its shared history panel
        # verbatim over an ICESEE-native manager (run_records.py-backed).
        # Results reuse the existing local figures/H5 preview; the DA-aware
        # ResultPackage (ensemble/analysis/RMSE) is a separate, larger port.
        # =========================================================
        icesee_runs_manager = IceseeRunsManager(root=_icesee_run_dir_base())

        def _on_icesee_run_selected(run_id):
            run = icesee_runs_manager.selected_run()
            if not (run and run.workspace_directory):
                return
            refresh_results_preview(run.workspace_directory, results_out)
            try:
                pkg = discover_result_package(run.workspace_directory)
                lines = pkg.summary_lines()
            except Exception:
                lines = []
            if lines:
                with results_out:
                    print("\nDA outputs (from results/*.h5):")
                    for line in lines:
                        print(" -", line)

        def _on_icesee_tail_selected_run():
            run = icesee_runs_manager.selected_run()
            log_out.clear_output()
            with log_out:
                print(icesee_runs_manager.tail(run.id) if run else "No run selected.")

        def _on_icesee_download_selected_results():
            run = icesee_runs_manager.selected_run()
            if not run:
                return
            zip_path = icesee_runs_manager.download_results(run.id)
            with log_out:
                if zip_path is not None:
                    display(FileLink(str(zip_path)))
                else:
                    print("[workspace] No local results captured for this run yet.")

        def _on_icesee_download_selected_figures():
            run = icesee_runs_manager.selected_run()
            if not run:
                return
            zip_path = icesee_runs_manager.download_figures(run.id)
            with log_out:
                if zip_path is not None:
                    display(FileLink(str(zip_path)))
                else:
                    print("[workspace] No local figures captured for this run yet.")

        icesee_history_panel = build_workspace_history_panel(
            manager=icesee_runs_manager,
            on_run_selected=_on_icesee_run_selected,
            on_tail_log=_on_icesee_tail_selected_run,
            on_download=_on_icesee_download_selected_results,
            on_show_figures=_on_icesee_download_selected_figures,
            defer_initial_load=True,
        )
        # The single Workspace (Runs/Files/Run Log/Results) is assembled at
        # the end of this function via the SAME shared build_run_details/
        # build_workspace_explorer CryoLauncher uses -- not a second,
        # ICESEE-only Accordion presentation.

        # =========================================================
        # Run Plan -- the CryoLauncher semantic separation (execution mode
        # / compute backend / model environment / model / provenance),
        # reusing the SAME shared composition panel (build_run_plan_panel),
        # with ICESEE's DA identity (DAIdentity.summary_rows(), already
        # built in run_records.py) as first-class rows, not flattened away.
        # =========================================================
        run_plan_summary_html = W.HTML()
        run_plan_command_html = W.HTML(
            "<div class='icesee-subtle'>The exact command is shown in Run "
            "log after Run -- it depends on live choices (connector vs "
            "direct SSH, spack vs container, existing sbatch, etc.) this "
            "preview does not simulate.</div>"
        )

        def _update_icesee_run_plan_summary(_=None):
            mode = get_mode()
            mode_label = {
                MODE_LOCAL: "Local", MODE_REMOTE: "Remote", MODE_CLOUD: "Cloud",
            }.get(mode, mode)
            backend_label = {
                MODE_LOCAL: "Local (GHUB)",
                MODE_REMOTE: {"spack": "ICESEE-Spack", "container": "ICESEE-Container"}
                    .get(exec_backend_choice.value, exec_backend_choice.value),
                MODE_CLOUD: "AWS Batch",
            }.get(mode, mode)
            model_environment = {
                MODE_LOCAL: "ICESEE (native Python)",
                MODE_REMOTE: backend_label,
                MODE_CLOUD: "AWS Batch container",
            }.get(mode, "")
            rows = [
                ("Execution mode", mode_label),
                ("Compute backend", backend_label),
                ("Model environment", model_environment),
            ]
            try:
                identity = da_identity_from_params(build_config_from_widgets())
                rows += identity.summary_rows()
            except Exception:
                pass    # a mid-edit params.yaml must never break the summary
            run_plan_summary_html.value = (
                "<div class='cryostack-selected-run-card'>"
                + "".join(
                    f"<div><span>{html_lib.escape(label)}</span>"
                    f"<b>{html_lib.escape(str(value))}</b></div>"
                    for label, value in rows if value
                )
                + "</div>"
            )

        icesee_run_plan = build_run_plan_panel(
            summary_widget=run_plan_summary_html,
            command_widget=run_plan_command_html,
        )
        mode_tabs.observe(_update_icesee_run_plan_summary, names="selected_index")
        exec_backend_choice.observe(_update_icesee_run_plan_summary, names="value")
        example_dd.observe(_update_icesee_run_plan_summary, names="value")
        filter_alg_dd.observe(_update_icesee_run_plan_summary, names="value")
        ens_sl.observe(_update_icesee_run_plan_summary, names="value")

        # ssh_key_manager_box = W.Accordion(children=[ssh_key_manager])
        # # ssh_key_manager_box.set_title(0, "🔐 SSH Key Manager")
        # ssh_key_manager_box.set_title(0, "🔐 Server-side SSH Key Manager")
        # ssh_key_manager_box.selected_index = None

        # Remote panel. Authentication + the connector card + "Open Connector
        # Setup" now live inside the Remote connection panel (B4). "Check SSH
        # Access" is the panel's primary action. Status / Tail / Terminate are
        # NOT duplicated here -- Status/Tail live in the Workspace Run Log
        # toolbar and Terminate lives in the Execution panel, matching
        # CryoLauncher's own placement exactly (only "Check SSH"-style connect
        # actions are ever duplicated, into the Workspace toolbar).
        remote_box = W.VBox(
            [
                W.HTML("<div class='icesee-h'>Remote</div>"),
                remote_conn_box,
                exec_backend_box,
                slurm_box,
                ssh_key_manager_box,
            ],
            layout=W.Layout(gap="8px"),
        )

        # Cloud panel -- Submit is this panel's own action (the same
        # structural role CryoLauncher's cloud_environment "Launch cloud run"
        # plays: mode-specific, not the generic Execution surface). Status/
        # Logs live in the Workspace Run Log toolbar; Terminate lives in the
        # Execution panel -- neither is duplicated here.
        cloud_panel = W.VBox(
            [
                W.HTML("<div class='icesee-h'>Cloud</div>"),
                W.HTML("<div class='icesee-subtle'>AWS Batch backend via AWS CLI.</div>"),
                W.HBox([W.HTML("<div class='icesee-lbl'>Region:</div>"), aws_region, W.HTML("<div class='icesee-lbl'>Profile:</div>"), aws_profile],
                    layout=W.Layout(gap="12px")),
                W.HBox([W.HTML("<div class='icesee-lbl'>S3 prefix:</div>"), cloud_bucket], layout=W.Layout(gap="12px")),
                W.HTML("<div class='icesee-subtle' style='margin-top:10px'>AWS Batch</div>"),
                W.HBox([W.HTML("<div class='icesee-lbl'>Queue:</div>"), batch_job_queue], layout=W.Layout(gap="12px")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Job def:</div>"), batch_job_def], layout=W.Layout(gap="12px")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Job name:</div>"), batch_job_name], layout=W.Layout(gap="12px")),
                W.HBox([cloud_submit_btn], layout=W.Layout(gap="10px")),
            ],
            layout=W.Layout(gap="8px"),
        )
        cloud_panel.add_class("icesee-card")

        mode_tabs.children = [local_tab_card, remote_box, cloud_panel]
        mode_tabs.set_title(0, "Local (GHUB)")
        mode_tabs.set_title(1, "Remote")
        mode_tabs.set_title(2, "Cloud")

        local_tab_card.layout = W.Layout(width="100%")
        remote_box.layout   = W.Layout(width="100%")
        cloud_panel.layout     = W.Layout(width="100%")

        # Workspace Run Log toolbar: swapped by execution mode, exactly the
        # CryoLauncher pattern (log_runtime_controls in icesheets_gateway.py)
        # -- status/tail/connect-type diagnostics live here, never in the
        # scientific config panel, and never a second time in Execution.
        log_runtime_controls = build_workspace_toolbar([])

        def _toggle_panels_from_tabs(_=None):
            mode = get_mode()

            is_remote = (mode == MODE_REMOTE)
            connect_btn.disabled = not is_remote
            submit_btn.disabled = not is_remote
            status_btn.disabled = not is_remote
            tail_btn.disabled = not is_remote
            terminate_btn.disabled = not is_remote
            terminate_btn.layout.display = "" if is_remote else "none"

            is_cloud = (mode == MODE_CLOUD)
            cloud_submit_btn.disabled = not is_cloud
            cloud_status_btn.disabled = not is_cloud
            cloud_logs_btn.disabled = not is_cloud
            cloud_terminate_btn.disabled = not is_cloud
            cloud_terminate_btn.layout.display = "" if is_cloud else "none"

            # Cloud has its own dedicated Submit (cloud_submit_btn, inside the
            # Cloud panel) -- the generic Execution Run button is hidden for
            # Cloud, the same rule CryoLauncher's run_btn follows for its own
            # cloud path (a lesson from a real live-acceptance bug: two submit
            # surfaces for the same job).
            action_btn.layout.display = "none" if is_cloud else ""

            if is_remote:
                log_runtime_controls.children = (connect_btn, status_btn, tail_btn, clear_btn)
            elif is_cloud:
                log_runtime_controls.children = (cloud_status_btn, cloud_logs_btn, clear_btn)
            else:
                log_runtime_controls.children = (clear_btn,)

            update_action_button()

        mode_tabs.observe(_toggle_panels_from_tabs, names="selected_index")
        _toggle_panels_from_tabs()

        exec_backend_choice.observe(_toggle_exec_backend_ui, names="value")
        _toggle_exec_backend_ui()

        log_out.add_class("icesee-out")
        results_out.add_class("icesee-out")

        # =========================================================
        # Application shell -- GENUINELY the same shell CryoLauncher uses,
        # not an ICESEE imitation of it: build_run_settings_panel (Run
        # settings, with Run Plan nested as its last child, exactly
        # CryoLauncher's own composition), build_runtime_panel (Execution:
        # state + submit/terminate), build_run_details (the one Workspace:
        # Runs/Files/Run Log/Results), build_workspace_explorer (the
        # top-level two-column shell). ICESEE's Remote/Cloud content already
        # lives inside mode_tabs (a structural difference CryoLauncher does
        # not have -- its Remote/Cloud panels are simultaneously-present,
        # visibility-toggled VBoxes); build_run_settings_panel's own
        # remote_panel/cloud_panel slots are therefore inert placeholders
        # here, not a second copy of that content.
        # =========================================================
        icesee_run_settings = build_run_settings_panel(
            configuration_rows=[
                W.HBox([W.HTML("<div class='icesee-lbl'>Mode:</div>"), mode_tabs], layout=W.Layout(gap="8px", width="100%")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Example:</div>"), example_dd], layout=W.Layout(gap="8px", width="100%")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Preset:</div>"), preset_dd], layout=W.Layout(gap="8px", width="100%")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Filter:</div>"), filter_alg_dd], layout=W.Layout(gap="8px", width="100%")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Output:</div>"), output_label_dd], layout=W.Layout(gap="8px", width="100%")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Ens:</div>"), ens_sl], layout=W.Layout(gap="8px", width="100%")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Seed:</div>"), seed_in], layout=W.Layout(gap="8px", width="100%")),
                W.Box([gen_report], layout=W.Layout(margin="6px 0 0 120px")),
                W.Box([open_latest], layout=W.Layout(margin="0 0 8px 120px")),
                W.HTML("<div class='icesee-subtle' style='margin:8px 0 8px'>Full configuration (from <code>params.yaml</code>)</div>"),
                params_holder,
            ],
            remote_panel=W.HTML(""),   # Remote content already lives in mode_tabs above
            cloud_panel=W.HTML(""),    # Cloud content already lives in mode_tabs above
            run_plan=icesee_run_plan.container,
        )

        icesee_runtime = build_runtime_panel(
            status_widget=status_chip,
            run_button=action_btn,
            remote_terminate_button=terminate_btn,
            cloud_terminate_button=cloud_terminate_btn,
        )

        icesee_workspace = build_run_details(
            log_output=log_out,
            results_output=results_out,
            download_controls=download_buttons_row,
            log_controls=log_runtime_controls,
            runs_panel=icesee_history_panel.runs_panel,
            files_panel=icesee_history_panel.files_panel,
        )

        icesee_shell = build_workspace_explorer(
            run_settings=icesee_run_settings,
            runtime=icesee_runtime.container,
            run_details=icesee_workspace.container,
        )

        page = W.VBox(
            [
                shared_styles,
                W.HTML(css),

                experiment_bridge.widget(),
                workspace_bridge.widget(),

                app_menu,
                header,
                icesee_shell.container,
                icesee_shell.height_sync,
                back_link,
            ],
            layout=W.Layout(width="100%"),
        )
        page.add_class("icesee-page")

        set_status("idle")
        rebuild_for_example()
        _update_icesee_run_plan_summary()

        # B2: restore this user's saved per-resource settings, last of all.
        try:
            with perf.span("workspace hydrate"), ui_refresh.batch():
                _b2_warnings = resource_state.hydrate()
                _sync_resource_facts()
            for _w in _b2_warnings:
                with log_out:
                    print("[settings]", _w)
        except Exception as _b2_err:
            with log_out:
                print("[settings] restore skipped:", type(_b2_err).__name__, _b2_err)

        perf.mark("gateway total (icesee)", _time.perf_counter() - _perf_t0)
        return page
    except Exception as e:
        import traceback
        print("ERROR:", e)
        traceback.print_exc()
        raise

