from __future__ import annotations

from dataclasses import dataclass
import html

import ipywidgets as W


@dataclass
class WorkspaceHistoryPanel:
    runs_panel: W.VBox
    files_panel: W.VBox
    refresh_button: W.Button
    runs: W.Select
    run_cards: W.VBox
    tail_button: W.Button
    download_button: W.Button
    figures_button: W.Button


def build_workspace_history_panel(
    *, manager, on_run_selected=None, defer_initial_load=False,
    on_tail_log=None, on_show_figures=None, on_download=None,
) -> WorkspaceHistoryPanel:
    """Runs is the selection/control surface for the shared selected run.

    ``on_tail_log`` / ``on_show_figures`` / ``on_download`` let the host route
    the Selected-Run actions through the existing Workspace machinery (switch
    the Run Log / Results tab, then invoke the existing tail / preview path).
    Without them the buttons fall back to the manager's own tail / download.
    """
    refresh_button = W.Button(description="Refresh", icon="refresh", layout=W.Layout(width="100px"))
    runs = W.Select(layout=W.Layout(display="none"))
    run_cards = W.VBox(layout=W.Layout(width="100%", gap="2px"))
    selected = W.HTML("<div class='icesee-subtle'>No run selected.</div>")
    files = W.HTML("<div class='icesee-subtle'>Select a run to inspect its workspace.</div>")
    tail_button = W.Button(description="Tail Log", icon="file-text")
    download_button = W.Button(description="Download", icon="download")
    figures_button = W.Button(description="Figures", icon="image")
    confirm = W.Checkbox(description="Confirm deletion of selected run", indent=False)
    delete_button = W.Button(description="Delete", icon="trash", button_style="danger", disabled=True)
    suppress_selection_reconcile = False

    def status_badge(status):
        value = str(status or "unknown").lower()
        return f"<span class='cryostack-run-badge cryostack-run-badge-{value}'>{value.title()}</span>"

    def _aws_diagnostics_html(run) -> str:
        """AWS console links for a cloud run, built PURELY from THIS run's
        persisted metadata['aws_resources'] -- never the current Cloud
        Environment defaults, and never an AWS call."""
        resources = (getattr(run, "metadata", None) or {}).get("aws_resources") or {}
        if not resources:
            return ""
        try:
            from cryostack_src.frontend.cryolauncher.cloud_environment import (
                aws_diagnostics_html,
            )
            snippet = aws_diagnostics_html(resources)
        except Exception:  # noqa: BLE001 - a link menu must never break the card
            return ""
        if not snippet:
            return ""
        return ("<div class='cryostack-section-label cryostack-selected-label'>"
                "AWS diagnostics</div>"
                "<div class='cryostack-selected-run-card'>" + snippet + "</div>")

    def software_stack_html(run) -> str:
        container = getattr(run, "container", None) or {}
        software = getattr(run, "software", None) or {}
        if not container and not software:
            return ""
        rows = ["<div class='cryostack-section-label cryostack-selected-label'>Software stack</div>",
                "<div class='cryostack-selected-run-card'>"]

        ref = container.get("reference")
        bp = container.get("build_provenance") or {}
        if not ref and container.get("source") == "git":
            ref = "ICESEE-Containers build"
        rows.append(f"<div><span>Container</span><b>{html.escape(str(ref or container.get('source') or '—'))}</b></div>")

        digest = container.get("digest")
        if digest:
            rows.append(f"<div><span>Digest</span><b>{html.escape(digest)}</b></div>")
        elif container:
            note = "not applicable" if bp.get("digest_status") == "not-applicable" else "unresolved"
            rows.append(f"<div><span>Digest</span><b class='cryostack-stack-lock'>{note}</b></div>")

        for key, sw in sorted(software.items()):
            src = sw.get("source", "?")
            commit = sw.get("resolved_commit")
            short = commit[:8] if commit else "unknown"
            if src == "image":
                detail = f"image · {sw.get('version') or '—'} · {short}"
            else:
                req = sw.get("requested_ref") or "?"
                detail = f"git · {req} → {short}"
            rows.append(f"<div><span>{html.escape(key.upper())}</span><b>{html.escape(detail)}</b></div>")

        rows.append("</div>")
        return "".join(rows)

    def render_cards(discovered):
        cards = []
        for run in discovered:
            job = str(run.jobid or "—")
            short_job = job if len(job) <= 12 else f"…{job[-11:]}"
            choose = W.Button(
                description=f"{run.model.upper()}  ·  {run.created:%Y-%m-%d %H:%M}",
                tooltip=f"Select run {run.id}",
                layout=W.Layout(flex="1 1 auto", min_width="0"),
            )
            choose.add_class("cryostack-run-select")
            row = W.HBox(
                [choose, W.HTML(status_badge(run.status)), W.HTML(f"<span class='cryostack-run-job'>#{short_job}</span>")],
                layout=W.Layout(width="100%", align_items="center", gap="7px"),
            )
            row.add_class("cryostack-run-row")
            if run.id == runs.value:
                row.add_class("cryostack-run-row-selected")
            choose.on_click(lambda _, run_id=run.id: setattr(runs, "value", run_id))
            cards.append(row)
        run_cards.children = tuple(cards) if cards else (
            W.HTML("<div class='icesee-subtle cryostack-runs-empty'>No previous runs found.</div>"),
        )

    def refresh(_=None, *, auto_select=True):
        nonlocal suppress_selection_reconcile
        previously_selected = manager.selected_run() if hasattr(manager, "selected_run") else None
        discovered = manager.refresh()
        runs.options = [
            (f"{run.model.upper()} • {run.created:%Y-%m-%d} • {run.status.title()}", run.id)
            for run in discovered
        ] or [("No previous runs found", "")]
        run_ids = {run.id for run in discovered}
        suppress_selection_reconcile = True
        try:
            if discovered and auto_select:
                runs.value = previously_selected.id if previously_selected and previously_selected.id in run_ids else discovered[0].id
            elif not discovered:
                runs.value = ""
        finally:
            suppress_selection_reconcile = False
        render_cards(discovered)
        if auto_select:
            # per-run inspection (reconcile, workspace file tree, viz render) is
            # only done for an explicitly selected run -- not on every gateway
            # build. Deferring it keeps the run list instant while a run with a
            # large workspace no longer stalls page load.
            show_selection()
        elif discovered:
            selected.value = (
                "<div class='icesee-subtle'>"
                f"{len(discovered)} previous run(s). Select one to inspect its "
                "workspace and results.</div>"
            )

    def show_selection(change=None):
        run = manager.select_run(runs.value or "")
        if run and not suppress_selection_reconcile:
            run = manager.reconcile_run(run.id)
        confirm.value = False
        if not run:
            selected.value = "<div class='icesee-subtle'>No run selected.</div>"
            files.value = "<div class='icesee-subtle'>Select a run to inspect its workspace.</div>"
            return
        _backend_label = {
            "aws": "AWS Batch (Fargate)",
        }.get((run.backend or "").strip().lower(), run.backend)
        _mode_label = {
            "cloud": "Cloud", "remote": "Remote", "local": "Local",
        }.get((run.execution_mode or "").strip().lower(), run.execution_mode)
        selected.value = (
            "<div class='cryostack-selected-run-card'>"
            f"<div><span>Model</span><b>{html.escape(run.model.upper())}</b></div>"
            f"<div><span>Backend</span><b>{html.escape(_backend_label)}</b></div>"
            f"<div><span>Execution</span><b>{html.escape(_mode_label)}</b></div>"
            f"<div><span>Job ID</span><b>{html.escape(str(run.jobid or '—'))}</b></div>"
            f"<div><span>Status</span>{status_badge(run.status)}</div>"
            "</div>"
            + software_stack_html(run)
            + _aws_diagnostics_html(run)
        )
        paths = manager.files(run.id)
        labels = [str(path.relative_to(run.workspace_directory)) for path in paths]
        if labels:
            files.value = (
                "<pre class='cryostack-workspace-tree'>"
                + "\n".join(f"├── {html.escape(label)}" for label in labels)
                + "</pre>"
            )
        else:
            files.value = "<div class='icesee-subtle'>(workspace files unavailable)</div>"
        render_cards(manager.list_runs())
        if on_run_selected is not None:
            try:
                on_run_selected(run.id)
            except Exception:  # noqa: BLE001 - a viz refresh must never break run selection
                pass

    def tail(_):
        if not runs.value:
            return
        if on_tail_log is not None:
            on_tail_log()                       # host: select + switch tab + tail
        else:
            manager.tail(runs.value)

    def download(_):
        if not runs.value:
            return
        if on_download is not None:
            on_download()
        else:
            manager.select_run(runs.value)
            manager.download_results(runs.value)

    def figures(_):
        if not runs.value:
            return
        if on_show_figures is not None:
            on_show_figures()                   # host: select + switch tab + preview
        else:
            manager.select_run(runs.value)
            manager.download_figures(runs.value)

    def delete(_):
        if runs.value and confirm.value and manager.delete_run(runs.value):
            refresh()

    refresh_button.on_click(refresh)
    runs.observe(show_selection, names="value")
    confirm.observe(lambda change: setattr(delete_button, "disabled", not change["new"]), names="value")
    tail_button.on_click(tail)
    download_button.on_click(download)
    figures_button.on_click(figures)
    delete_button.on_click(delete)

    runs_panel = W.VBox([
        W.HBox([W.HTML("<div class='cryostack-section-label'>Runs</div>"), refresh_button], layout=W.Layout(justify_content="space-between", align_items="center")),
        runs, run_cards,
        W.HTML("<div class='cryostack-section-label cryostack-selected-label'>Selected Run</div>"),
        selected,
        W.HBox([tail_button, download_button, figures_button], layout=W.Layout(gap="8px", flex_wrap="wrap")),
        W.VBox([confirm, delete_button], layout=W.Layout(gap="4px")),
    ], layout=W.Layout(width="100%", min_height="0", gap="7px"))
    files_panel = W.VBox(
        [files],
        layout=W.Layout(width="100%", min_height="0"),
    )
    refresh(auto_select=not defer_initial_load)
    return WorkspaceHistoryPanel(
        runs_panel=runs_panel,
        files_panel=files_panel,
        refresh_button=refresh_button,
        runs=runs,
        run_cards=run_cards,
        tail_button=tail_button,
        download_button=download_button,
        figures_button=figures_button,
    )
