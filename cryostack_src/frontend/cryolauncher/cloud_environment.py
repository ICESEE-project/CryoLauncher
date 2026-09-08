# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : ICESEE Cloud Environment
# File        : cloud_environment.py
#
# Description :
#     Provides the Cloud Environment panel used by the ICESEE frontend.
#     The component presents user-facing cloud configuration and keeps
#     infrastructure-specific settings inside an Advanced section.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-25
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
ICESEE Cloud Environment frontend component.

This module contains presentation and widget state only. It does not
perform cloud authentication, provisioning, submission, or other backend
operations.
"""

from __future__ import annotations

from dataclasses import dataclass

import ipywidgets as W

from cryostack_src.frontend.shared import (
    primary_button,
    secondary_button,
    status_badge,
    toolbar,
)


@dataclass
class CloudEnvironmentWidgets:
    """
    Widget references exposed to the gateway.

    Existing gateway callbacks can continue reading and writing these
    widgets during the frontend migration.
    """

    provider: W.Dropdown
    region: W.Text
    profile: W.Text

    s3_prefix: W.Text
    job_queue: W.Text
    job_definition: W.Text
    job_name: W.Text
    matlab_license_arn: W.Text
    matlab_license_save_button: W.Button

    account_status: W.HTML
    storage_status: W.HTML
    registry_status: W.HTML
    compute_status: W.HTML

    test_button: W.Button
    prepare_button: W.Button

    advanced: W.Accordion

    container: W.VBox

    # -- "Connect AWS Account" onboarding (C7.2) --------------------------
    #: the whole AWS ACCOUNT block (status line + connect card)
    aws_account_section: W.VBox
    #: "● Connected" / "● Not connected" badge line
    aws_account_status: W.HTML
    #: account id / region / access / last-verified (connected) OR the
    #: short "use your own account" explainer (disconnected)
    aws_account_detail: W.HTML
    #: disconnected -> reveals the 3-step card
    connect_button: W.Button
    #: the collapsible 3-step card (hidden until Connect is clicked)
    connect_form: W.VBox
    #: the Re-check / Disconnect row shown only when connected
    connect_actions: W.HBox
    #: an <a target="_blank"> to the CloudFormation Quick Create page
    open_setup_link: W.HTML
    #: the ONLY value a user may need to paste back
    role_arn_input: W.Text
    verify_button: W.Button
    #: connected -> re-run AssumeRole with the stored role ARN
    recheck_button: W.Button
    #: connected -> remove the (non-secret) connection metadata
    disconnect_button: W.Button
    #: error (verification failed) -> the Retry connection / Change AWS
    #: account row -- the recovery escape hatch for a stranded connection
    recovery_actions: W.HBox
    #: repair/re-verify THIS account -- reopens the form, reusing the saved
    #: ExternalId, and prepopulates the saved Role ARN
    retry_button: W.Button
    #: abandon this local connection attempt and start onboarding a
    #: different AWS account (mints a fresh ExternalId; no AWS resources of
    #: the previous account are touched)
    change_account_button: W.Button
    #: -- staged "Change AWS account" (does NOT touch the active connection
    #: until the replacement itself verifies) ------------------------------
    #: the whole "connecting a new AWS account" card; hidden until
    #: change_account_button starts it, hidden again on Cancel or success
    change_account_panel: W.VBox
    #: explains the current active connection is untouched + warns about
    #: reusing the same AWS console session (AlreadyExistsException)
    change_account_notice: W.HTML
    #: shows the pending attempt's own verification error, if any
    change_account_status: W.HTML
    change_setup_link: W.HTML
    change_role_arn_input: W.Text
    change_verify_button: W.Button
    #: abandon the staged attempt; the active connection is untouched
    change_cancel_button: W.Button

    # -- RUN ESTIMATE + Review & Launch (C7.4) --------------------------
    #: compact "expected runtime · resources · estimated cost" block
    run_estimate_section: W.VBox
    run_estimate_line: W.HTML
    review_button: W.Button
    #: the REVIEW CLOUD RUN surface (hidden until Review & Launch)
    review_panel: W.VBox
    review_body: W.HTML
    review_notice: W.HTML
    review_back_button: W.Button
    launch_button: W.Button

    # -- CLOUD RUN active-run surface (C7.5) ---------------------------
    #: compact live status card, hidden until a run is launched
    active_run_section: W.VBox
    active_run_title: W.HTML
    active_run_status: W.HTML
    active_run_detail: W.HTML
    active_run_diagnostics: W.HTML
    active_run_actions: W.HBox
    active_run_log_button: W.Button
    active_run_results_button: W.Button
    active_run_terminate_button: W.Button


def _status_row(
    label: str,
    *,
    state: str = "idle",
    text: str = "Not prepared",
) -> tuple[W.HBox, W.HTML]:

    status = W.HTML(
        value=status_badge(
            state,
            label=text,
        ),
        layout=W.Layout(
            width="auto",
        ),
    )

    row = W.HBox(
        [
            W.HTML(
                value=(
                    f"""
                    <div
                      style="
                        font-size:12px;
                        color:#66758d;
                        min-width:130px;
                      "
                    >
                      {label}
                    </div>
                    """
                ),
                layout=W.Layout(
                    width="140px",
                ),
            ),
            status,
        ],
        layout=W.Layout(
            width="100%",
            align_items="center",
            gap="8px",
            padding="3px 0",
        ),
    )

    return row, status


def set_cloud_status(
    widget: W.HTML,
    *,
    state: str,
    label: str,
) -> None:
    """
    Update one Cloud Environment status indicator.
    """

    widget.value = status_badge(
        state,
        label=label,
    )


_DISCONNECTED_BLURB = (
    "Use your own AWS account and credits. CryoStack uses temporary role "
    "access and does not store your AWS access keys."
)


def _build_aws_account_section() -> dict:
    """The AWS ACCOUNT block: a status line plus the collapsible 3-step
    "Connect your AWS account" card. Contains no access-key / secret field --
    the only value a user may paste back is the Role ARN."""

    aws_account_status = W.HTML(
        value=status_badge("idle", label="Not connected"),
    )

    aws_account_detail = W.HTML(
        value=(
            f"<div style='font-size:11px;color:#66758d;line-height:1.45;'>"
            f"{_DISCONNECTED_BLURB}</div>"
        ),
    )

    connect_button = primary_button("Connect AWS Account", icon="aws")

    open_setup_link = W.HTML(
        value=(
            "<span style='font-size:11px;color:#96a1b4;'>"
            "Setup link appears after you start…</span>"
        ),
    )

    role_arn_input = W.Text(
        description="Role ARN:",
        placeholder="arn:aws:iam::<account>:role/CryoStackExecutionRole",
        layout=W.Layout(width="100%"),
        style={"description_width": "110px"},
    )

    verify_button = primary_button("Verify connection", icon="check")

    steps = W.HTML(
        value="""
        <div style="font-size:12px;font-weight:700;color:#172033;margin-bottom:4px;">
          CONNECT YOUR AWS ACCOUNT
        </div>
        <ol style="font-size:11px;color:#66758d;line-height:1.6;margin:0 0 6px 16px;padding:0;">
          <li>Open AWS setup</li>
          <li>Create the CryoStack access role</li>
          <li>Return here and verify</li>
        </ol>
        """,
    )

    connect_form = W.VBox(
        [steps, open_setup_link, role_arn_input, verify_button],
        layout=W.Layout(
            width="100%",
            gap="6px",
            padding="8px",
            border="1px solid #dfe6ef",
            display="none",           # revealed on Connect
        ),
    )

    recheck_button = secondary_button("Re-check", icon="refresh")
    disconnect_button = secondary_button("Disconnect", icon="unlink")

    connect_actions = W.HBox(
        [recheck_button, disconnect_button],
        layout=W.Layout(gap="8px", display="none"),
    )

    # -- failed-verification recovery: shown ONLY in the "error" state ---
    retry_button = primary_button("Retry connection", icon="redo")
    change_account_button = secondary_button("Change AWS account", icon="exchange")

    recovery_actions = W.HBox(
        [retry_button, change_account_button],
        layout=W.Layout(gap="8px", display="none"),
    )

    # -- staged "Change AWS account" card: separate from connect_form so it
    # can be shown ALONGSIDE the still-active connection's own status ------
    change_account_notice = W.HTML(
        value=(
            "<div style='font-size:11px;color:#66758d;line-height:1.5;'>"
            "Your current connection above is kept until this new one "
            "verifies. If your browser is still signed into AWS as the "
            "<b>same</b> account, use <b>Retry connection</b> instead -- "
            "creating another CryoStack access role in an account that "
            "already has one fails with <code>AlreadyExistsException</code>."
            "</div>"
        ),
    )
    change_setup_link = W.HTML(
        value=(
            "<span style='font-size:11px;color:#96a1b4;'>"
            "Setup link appears after you start…</span>"
        ),
    )
    change_role_arn_input = W.Text(
        description="Role ARN:",
        placeholder="arn:aws:iam::<account>:role/CryoStackExecutionRole",
        layout=W.Layout(width="100%"),
        style={"description_width": "110px"},
    )
    change_account_status = W.HTML()
    change_verify_button = primary_button("Verify new account", icon="check")
    change_cancel_button = secondary_button("Cancel — back to current account", icon="ban")

    change_account_panel = W.VBox(
        [
            W.HTML(
                "<div style='font-size:12px;font-weight:700;color:#172033;"
                "margin-bottom:2px;'>CONNECTING A NEW AWS ACCOUNT</div>"
            ),
            change_account_notice,
            change_setup_link,
            change_role_arn_input,
            change_account_status,
            W.HBox([change_verify_button, change_cancel_button],
                   layout=W.Layout(gap="8px", flex_wrap="wrap")),
        ],
        layout=W.Layout(
            width="100%", gap="6px", padding="8px",
            border="1px solid #dfe6ef", display="none",   # revealed on Change AWS account
        ),
    )

    heading = W.HTML(
        value=(
            "<div style='font-size:12px;font-weight:700;color:#172033;"
            "letter-spacing:.02em;'>AWS ACCOUNT</div>"
        ),
    )

    aws_account_section = W.VBox(
        [
            heading,
            aws_account_status,
            aws_account_detail,
            connect_button,
            connect_form,
            connect_actions,
            recovery_actions,
            change_account_panel,
        ],
        layout=W.Layout(width="100%", gap="5px", padding="6px 0"),
    )

    return {
        "aws_account_section": aws_account_section,
        "aws_account_status": aws_account_status,
        "aws_account_detail": aws_account_detail,
        "connect_button": connect_button,
        "connect_form": connect_form,
        "connect_actions": connect_actions,
        "open_setup_link": open_setup_link,
        "role_arn_input": role_arn_input,
        "verify_button": verify_button,
        "recheck_button": recheck_button,
        "disconnect_button": disconnect_button,
        "recovery_actions": recovery_actions,
        "retry_button": retry_button,
        "change_account_button": change_account_button,
        "change_account_panel": change_account_panel,
        "change_account_notice": change_account_notice,
        "change_account_status": change_account_status,
        "change_setup_link": change_setup_link,
        "change_role_arn_input": change_role_arn_input,
        "change_verify_button": change_verify_button,
        "change_cancel_button": change_cancel_button,
    }


def set_aws_account_view(
    widgets: "CloudEnvironmentWidgets",
    summary: dict,
    *,
    setup_url: str | None = None,
    form_open: bool | None = None,
) -> None:
    """Render the AWS ACCOUNT block from an ``AWSOnboarding.summary()`` dict.

    ``summary["status"]`` is one of ``disconnected`` / ``pending`` /
    ``connected`` / ``error``. Never renders any secret -- ``summary`` carries
    only non-secret connection metadata.
    """

    status = (summary or {}).get("status", "disconnected")
    detail = widgets.aws_account_detail

    if setup_url:
        widgets.open_setup_link.value = (
            f"<a href='{escape_attr(setup_url)}' target='_blank' rel='noopener' "
            "style='font-size:12px;font-weight:600;'>▶ Open AWS Setup</a>"
        )

    if form_open is not None:
        widgets.connect_form.layout.display = "flex" if form_open else "none"

    def _show_connected_actions(show: bool) -> None:
        widgets.connect_actions.layout.display = "flex" if show else "none"

    def _show_recovery_actions(show: bool) -> None:
        widgets.recovery_actions.layout.display = "flex" if show else "none"

    if status == "connected":
        widgets.aws_account_status.value = status_badge("done", label="Connected")
        acct = summary.get("account_id", "")
        region = summary.get("region", "")
        verified = summary.get("verified_at", "") or "just now"
        detail.value = (
            "<table style='font-size:11px;color:#66758d;border-collapse:collapse;'>"
            f"<tr><td style='padding:1px 12px 1px 0;'>Account ID</td><td><code>{escape_text(acct)}</code></td></tr>"
            f"<tr><td style='padding:1px 12px 1px 0;'>Region</td><td>{escape_text(region)}</td></tr>"
            "<tr><td style='padding:1px 12px 1px 0;'>Access</td><td>Temporary role</td></tr>"
            f"<tr><td style='padding:1px 12px 1px 0;'>Last verified</td><td>{escape_text(str(verified))}</td></tr>"
            "</table>"
        )
        widgets.connect_button.layout.display = "none"
        widgets.connect_form.layout.display = "none"
        _show_connected_actions(True)
        _show_recovery_actions(False)
        return

    if status == "error":
        widgets.aws_account_status.value = status_badge("fail", label="Not verified")
        reason = summary.get("status_reason", "") or "Verification failed."
        detail.value = (
            f"<div style='font-size:11px;color:#b23c3c;line-height:1.45;'>{escape_text(reason)}</div>"
        )
        widgets.connect_button.layout.display = "none"
        # The form (Role ARN + Verify) is NOT forced open here -- it stays at
        # whatever the caller last set it to (hidden by default; a prior
        # Retry/Verify in this session left it open). "Retry connection"
        # below is the explicit, discoverable way back into it, prepopulated
        # with the saved Role ARN -- a forgotten ARN is never a dead end.
        _show_connected_actions(False)
        _show_recovery_actions(True)
        return

    if status == "pending":
        widgets.aws_account_status.value = status_badge("running", label="Awaiting role")
        detail.value = (
            "<div style='font-size:11px;color:#66758d;line-height:1.45;'>"
            "Create the role in AWS, then paste the Role ARN below and verify."
            "</div>"
        )
        widgets.connect_button.layout.display = "none"
        widgets.connect_form.layout.display = "flex"
        _show_connected_actions(False)
        _show_recovery_actions(False)
        return

    # disconnected
    widgets.aws_account_status.value = status_badge("idle", label="Not connected")
    detail.value = (
        f"<div style='font-size:11px;color:#66758d;line-height:1.45;'>{_DISCONNECTED_BLURB}</div>"
    )
    widgets.connect_button.layout.display = "inline-flex"
    widgets.connect_form.layout.display = "none"
    _show_connected_actions(False)
    _show_recovery_actions(False)


def set_change_account_panel(
    widgets: "CloudEnvironmentWidgets",
    pending_summary: dict | None,
    *,
    setup_url: str | None = None,
    prefill_role_arn: bool = False,
) -> None:
    """Render the staged "Connecting a new AWS account" card.

    Independent of :func:`set_aws_account_view` -- the active connection's
    own status is rendered separately and is NEVER touched by this function.
    ``pending_summary`` is ``None`` when there is no staged replacement (the
    panel is hidden); otherwise it is the pending connection's own
    ``pending``/``error`` summary. ``prefill_role_arn`` restores a Role ARN
    already saved on the pending attempt (e.g. after a failed Verify, or on
    a page reload) -- never on a fresh Cancel, which clears the field.
    """
    if pending_summary is None:
        widgets.change_account_panel.layout.display = "none"
        return

    widgets.change_account_panel.layout.display = "flex"

    if setup_url:
        widgets.change_setup_link.value = (
            f"<a href='{escape_attr(setup_url)}' target='_blank' rel='noopener' "
            "style='font-size:12px;font-weight:600;'>▶ Open AWS Setup</a>"
        )

    if prefill_role_arn:
        widgets.change_role_arn_input.value = pending_summary.get("role_arn", "") or ""

    if pending_summary.get("status") == "error":
        reason = pending_summary.get("status_reason", "") or "Verification failed."
        widgets.change_account_status.value = (
            f"<div style='font-size:11px;color:#b23c3c;line-height:1.45;'>{escape_text(reason)}</div>"
        )
    else:
        widgets.change_account_status.value = ""


def escape_text(value: str) -> str:
    from html import escape

    return escape(str(value or ""))


def escape_attr(value: str) -> str:
    from html import escape

    return escape(str(value or ""), quote=True)


# ---------------------------------------------------------------------------
# RUN ESTIMATE + Review & Launch (C7.4)
# ---------------------------------------------------------------------------
_BILLING_NOTE = (
    "This is an estimate. AWS charges apply to your AWS account. AWS "
    "promotional/free-tier credits, billing rules and payment methods are "
    "managed by AWS &mdash; check your AWS Billing &amp; Cost Management "
    "console for your credit balance. CryoStack cannot guarantee a run is "
    "covered by those credits."
)


def _build_run_estimate_section() -> dict:
    """The compact RUN ESTIMATE block shown once infrastructure is Ready, plus
    the (hidden) REVIEW CLOUD RUN surface."""

    heading = W.HTML(
        value=(
            "<div style='font-size:12px;font-weight:700;color:#172033;"
            "letter-spacing:.02em;margin-top:2px;'>RUN ESTIMATE</div>"
        ),
    )
    run_estimate_line = W.HTML(
        value=(
            "<div style='font-size:11px;color:#96a1b4;'>"
            "Prepare the cloud environment to see an estimate.</div>"
        ),
    )
    review_button = primary_button("Review & Launch", icon="clipboard-check")

    run_estimate_section = W.VBox(
        [heading, run_estimate_line, review_button],
        layout=W.Layout(width="100%", gap="5px", padding="6px 0", display="none"),
    )

    # -- the review surface (hidden until Review & Launch) -----------
    review_body = W.HTML()
    review_notice = W.HTML(
        value=(
            f"<div style='font-size:10.5px;color:#66758d;line-height:1.5;"
            f"background:#f6f8fb;border:1px solid #e4e9f0;border-radius:6px;"
            f"padding:8px;margin:6px 0;'>{_BILLING_NOTE}</div>"
        ),
    )
    review_back_button = secondary_button("Back", icon="arrow-left")
    launch_button = primary_button("Launch cloud run", icon="cloud-upload-alt")

    review_panel = W.VBox(
        [
            W.HTML(
                "<div style='font-size:13px;font-weight:700;color:#172033;'>"
                "REVIEW CLOUD RUN</div>"
            ),
            review_body,
            review_notice,
            W.HBox([review_back_button, launch_button], layout=W.Layout(gap="8px")),
        ],
        layout=W.Layout(
            width="100%", gap="6px", padding="12px",
            border="1px solid #cbd6e4", background_color="#ffffff",
            display="none",
        ),
    )

    return {
        "run_estimate_section": run_estimate_section,
        "run_estimate_line": run_estimate_line,
        "review_button": review_button,
        "review_panel": review_panel,
        "review_body": review_body,
        "review_notice": review_notice,
        "review_back_button": review_back_button,
        "launch_button": launch_button,
    }


def set_run_estimate_view(
    widgets: "CloudEnvironmentWidgets",
    *,
    visible: bool,
    runtime_text: str = "",
    resource_text: str = "",
    cost_text: str = "",
    unavailable: bool = False,
) -> None:
    """Render the compact RUN ESTIMATE line. Shown only when infrastructure is
    Ready; hidden otherwise."""
    widgets.run_estimate_section.layout.display = "flex" if visible else "none"
    if not visible:
        return
    cost = (
        "<span style='color:#96a1b4;'>Cost estimate unavailable</span>"
        if unavailable
        else f"<b style='font-size:13px;color:#172033;'>{escape_text(cost_text)}</b>"
    )
    widgets.run_estimate_line.value = (
        "<div style='font-size:11px;color:#66758d;line-height:1.7;'>"
        f"Expected runtime&nbsp;&nbsp;{escape_text(runtime_text)}<br>"
        f"Resources&nbsp;&nbsp;{escape_text(resource_text)}<br>"
        f"Estimated cost&nbsp;&nbsp;{cost}"
        "</div>"
    )


def _yn(ready: bool) -> str:
    color = "#2f8f4e" if ready else "#b23c3c"
    return f"<span style='color:{color};'>{'Ready' if ready else 'Not ready'}</span>"


def set_review_panel(widgets: "CloudEnvironmentWidgets", review) -> None:
    """Render the REVIEW CLOUD RUN body from a ``CloudRunReview`` (no secrets)."""
    r = review
    infra = r.infrastructure
    basis = "".join(f"<div>{escape_text(line)}</div>" for line in r.estimate_basis_lines())
    blocked = ""
    if not r.can_launch:
        items = "".join(f"<li>{escape_text(x)}</li>" for x in r.blocked_reasons)
        blocked = (
            "<div style='font-size:11px;color:#b23c3c;background:#fdf1f1;"
            "border:1px solid #f0d5d5;border-radius:6px;padding:8px;margin-top:6px;'>"
            f"<b>Launch is blocked:</b><ul style='margin:4px 0 0 16px;padding:0;'>{items}</ul>"
            "</div>"
        )
    image_rows = ""
    if getattr(r, "image_reference", ""):
        ref = escape_text(r.image_reference)
        url = getattr(r, "image_public_url", "") or ""
        ref_html = (f"<a href='{escape_text(url)}' target='_blank' "
                    f"rel='noopener noreferrer'>{ref}</a>") if url else ref
        digest = escape_text(r.image_digest or "")
        short = (digest[:22] + "…") if digest.startswith("sha256:") else digest
        image_rows = (
            '<tr><td colspan="2" style="padding-top:6px;font-weight:700;'
            'color:#172033;">Container image</td></tr>'
            f'<tr><td style="padding:1px 12px 1px 0;">Image</td><td>{ref_html} '
            '<span style="color:#96a1b4;">· Tested</span></td></tr>'
            f'<tr><td style="padding:1px 12px 1px 0;">Digest</td>'
            f'<td><code style="font-size:10px;">{short or "—"}</code></td></tr>'
        )

    # ISSM only: a distinct readiness row -- "container image ready" is NOT
    # "ISSM runtime ready" (ISSM drives MATLAB, which needs a license
    # reachable from AWS).
    runtime_row = ""
    _issm_ready = getattr(r, "issm_runtime_ready", None)
    if _issm_ready is not None:
        val = (_yn(True) if _issm_ready
               else "<span style='color:#b23c3c;'>Needs a MATLAB license</span>")
        runtime_row = (
            '<tr><td style="padding:1px 12px 1px 0;">ISSM runtime</td>'
            f'<td>{val}</td></tr>'
        )

    widgets.review_body.value = f"""
      <table style="font-size:11px;color:#66758d;border-collapse:collapse;width:100%;">
        <tr><td colspan="2" style="padding-top:4px;font-weight:700;color:#172033;">Experiment</td></tr>
        <tr><td style="padding:1px 12px 1px 0;width:130px;">Model</td><td>{escape_text(r.model.upper())}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Example</td><td>{escape_text(r.example)}</td></tr>
        {image_rows}
        <tr><td colspan="2" style="padding-top:6px;font-weight:700;color:#172033;">AWS</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Account</td><td><code>{escape_text(r.account_id)}</code></td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Region</td><td>{escape_text(r.region)}</td></tr>
        <tr><td colspan="2" style="padding-top:6px;font-weight:700;color:#172033;">Resources</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">vCPU</td><td>{r.vcpu:g}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Memory</td><td>{r.memory_gib:g} GiB</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Time limit</td><td>{r.time_limit_minutes} min</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Expected runtime</td><td>~{_review_minutes(r.expected_runtime_minutes)} min</td></tr>
        <tr><td colspan="2" style="padding-top:6px;font-weight:700;color:#172033;">Estimated cost</td></tr>
        <tr><td style="padding:1px 12px 1px 0;"></td>
            <td><b style="font-size:14px;color:#172033;">{escape_text(r.cost_summary())}</b></td></tr>
        <tr><td style="padding:1px 12px 1px 0;vertical-align:top;">Estimate basis</td>
            <td style="font-size:10.5px;color:#8a94a6;">{basis}</td></tr>
        <tr><td colspan="2" style="padding-top:6px;font-weight:700;color:#172033;">Infrastructure</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Account</td><td>{_yn(infra.account)}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Storage</td><td>{_yn(infra.storage)}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Container image</td><td>{_yn(infra.container)}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Compute (AWS Batch)</td><td>{_yn(infra.compute)}</td></tr>
        {runtime_row}
      </table>
      {blocked}
    """
    widgets.launch_button.disabled = not r.can_launch


def show_review_panel(widgets: "CloudEnvironmentWidgets", visible: bool) -> None:
    widgets.review_panel.layout.display = "flex" if visible else "none"


def _review_minutes(minutes: float) -> str:
    m = float(minutes)
    return f"{m:.0f}" if m >= 1 else f"{m:.1f}"


# ---------------------------------------------------------------------------
# CLOUD RUN active-run surface (C7.5)
# ---------------------------------------------------------------------------
#: CryoStack run state -> (badge state, user-facing label)
_RUN_STATE_LABELS = {
    "staging": ("running", "Staging…"),
    "submitting": ("running", "Submitting…"),
    "queued": ("running", "Queued"),
    "running": ("running", "Running"),
    "completed": ("done", "Completed"),
    "failed": ("fail", "Failed"),
    "cancelled": ("idle", "Cancelled"),
}


def _build_active_run_section() -> dict:
    """The compact CLOUD RUN status card shown while a launched run is active
    (and on its terminal state). No AWS plumbing on this surface."""

    title = W.HTML()
    status = W.HTML()
    detail = W.HTML()
    diagnostics = W.HTML()      # AWS diagnostics menu -- pure links, no AWS call

    log_button = secondary_button("View log", icon="file-text")
    results_button = primary_button("View results", icon="chart-area")
    terminate_button = W.Button(description="Terminate", icon="stop",
                                button_style="danger",
                                layout=W.Layout(width="auto"))
    actions = W.HBox([log_button, results_button, terminate_button],
                     layout=W.Layout(gap="8px", flex_wrap="wrap"))

    section = W.VBox(
        [
            W.HTML("<div style='font-size:12px;font-weight:700;color:#172033;"
                   "letter-spacing:.02em;'>CLOUD RUN</div>"),
            title, status, detail, diagnostics, actions,
        ],
        layout=W.Layout(
            width="100%", gap="5px", padding="12px",
            border="1px solid #cbd6e4", background_color="#ffffff",
            display="none",
        ),
    )
    return {
        "active_run_section": section,
        "active_run_title": title,
        "active_run_status": status,
        "active_run_detail": detail,
        "active_run_diagnostics": diagnostics,
        "active_run_actions": actions,
        "active_run_log_button": log_button,
        "active_run_results_button": results_button,
        "active_run_terminate_button": terminate_button,
    }


def show_active_run(widgets: "CloudEnvironmentWidgets", visible: bool) -> None:
    widgets.active_run_section.layout.display = "flex" if visible else "none"


def aws_diagnostics_html(resources: dict | None) -> str:
    """The AWS diagnostics menu as an HTML snippet -- a labelled row of
    external links built PURELY from a run's persisted resource snapshot
    (:func:`cryostack_src.cloud.diagnostics.aws_console_links`). No AWS call.
    Empty string when nothing can be linked yet."""
    from cryostack_src.cloud.diagnostics import aws_console_links

    links = aws_console_links(resources)
    if not links:
        return ""
    items = " &nbsp;·&nbsp; ".join(
        f"<a href='{escape_text(x['url'])}' target='_blank' "
        f"rel='noopener noreferrer' title='{escape_text(x.get('detail') or '')}'>"
        f"{escape_text(x['label'])}</a>"
        for x in links
    )
    return (
        "<div style='font-size:10.5px;color:#66758d;margin-top:2px;'>"
        "<span style='color:#8a94a6;font-weight:600;'>AWS diagnostics</span> "
        "&nbsp; " + items + "</div>"
    )


def set_active_run_view(
    widgets: "CloudEnvironmentWidgets",
    *,
    model: str = "",
    example: str = "",
    state: str = "",
    account_id: str = "",
    region: str = "",
    resource_text: str = "",
    elapsed_text: str = "",
    cost_text: str = "",
    expected_text: str = "",
    image_reference: str = "",
    image_digest: str = "",
    image_label: str = "",
    aws_resources: dict | None = None,
) -> None:
    """Render the CLOUD RUN card. ``cost_text`` is a pre-formatted string
    ("<$0.01" / "$0.04" / "Unavailable") -- this function never prices, and
    the diagnostics menu it renders makes no AWS call."""
    badge_state, label = _RUN_STATE_LABELS.get(state, ("running", state or "…"))
    terminal = state in ("completed", "failed", "cancelled")
    running = state in ("staging", "submitting", "queued", "running")

    widgets.active_run_title.value = (
        f"<div style='font-size:12px;color:#66758d;'>"
        f"{escape_text(model.upper())} &middot; {escape_text(example)}</div>"
    )
    pulse = (
        "<span aria-hidden='true' style='display:inline-block;width:7px;"
        "height:7px;border-radius:50%;background:#2f6feb;margin-right:6px;"
        "animation:cryostackPulse 1.4s ease-in-out infinite;'></span>"
        "<style>@keyframes cryostackPulse{0%,100%{opacity:.3}50%{opacity:1}}</style>"
        if running else ""
    )
    widgets.active_run_status.value = (
        f"<div role='status' style='font-size:12px;'>{pulse}"
        f"{status_badge(badge_state, label=label)}</div>"
    )

    rows = [("AWS", f"Account {escape_text(account_id or '—')} &middot; "
                    f"{escape_text(region or '—')}"),
            ("Resources", escape_text(resource_text or "—"))]
    if image_reference:
        _short = image_digest[:19] + "…" if image_digest.startswith("sha256:") else ""
        rows.append(("Image",
                     f"<code style='font-size:10px;'>{escape_text(image_reference)}</code>"
                     + (f" <span style='color:#96a1b4;'>{escape_text(_short)}</span>"
                        if _short else "")))
    if not terminal:
        rows.append(("Elapsed", escape_text(elapsed_text or "00:00")))
        rows.append(("Estimated cost so far",
                     f"{escape_text(cost_text or '—')} "
                     "<span style='color:#96a1b4;'>(estimate)</span>"))
        rows.append(("Expected runtime", escape_text(expected_text or "—")))
    body = "".join(
        f"<tr><td style='padding:1px 12px 1px 0;color:#8a94a6;white-space:nowrap;'>"
        f"{k}</td><td style='color:#66758d;'>{v}</td></tr>"
        for k, v in rows
    )
    note = (
        "<div style='font-size:10px;color:#96a1b4;margin-top:4px;'>Estimated AWS "
        "usage cost. Promotional credits and billing are managed by AWS.</div>"
        if not terminal else ""
    )
    widgets.active_run_detail.value = (
        f"<table style='font-size:11px;border-collapse:collapse;'>{body}</table>{note}"
    )
    widgets.active_run_diagnostics.value = aws_diagnostics_html(aws_resources)

    widgets.active_run_terminate_button.layout.display = (
        "none" if terminal else "inline-flex"
    )
    widgets.active_run_results_button.disabled = state != "completed"


def build_cloud_environment_card(
    *,
    region: str = "us-east-2",
    profile: str = "",
    s3_prefix: str = "",
    job_queue: str = "",
    job_definition: str = "",
    job_name: str = "icesheets",
    matlab_license_secret_arn: str = "",
) -> CloudEnvironmentWidgets:
    """
    Build the ICESEE Cloud Environment panel.

    The default view contains only cloud settings meaningful to most
    users. Existing AWS infrastructure fields remain available under
    Advanced so current functionality is preserved.
    """

    # ---------------------------------------------------------
    # Primary cloud configuration
    # ---------------------------------------------------------

    provider_widget = W.Dropdown(
        description="Provider:",
        options=[
            ("Amazon Web Services", "aws"),
        ],
        value="aws",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "110px",
        },
    )

    region_widget = W.Text(
        description="Region:",
        value=region,
        placeholder="us-east-2",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "110px",
        },
    )

    # ---------------------------------------------------------
    # Environment state
    # ---------------------------------------------------------

    account_row, account_status = _status_row(
        "Account",
        state="idle",
        text="Not connected",
    )

    storage_row, storage_status = _status_row(
        "Storage",
        state="idle",
        text="Not prepared",
    )

    registry_row, registry_status = _status_row(
        "Containers",
        state="idle",
        text="Not prepared",
    )

    compute_row, compute_status = _status_row(
        "Compute",
        state="idle",
        text="Not prepared",
    )

    status_panel = W.VBox(
        [
            account_row,
            storage_row,
            registry_row,
            compute_row,
        ],
        layout=W.Layout(
            width="100%",
            gap="2px",
            padding="6px 0",
        ),
    )

    # ---------------------------------------------------------
    # Primary actions
    # ---------------------------------------------------------

    test_button = secondary_button(
        "Test connection",
        icon="plug",
    )

    prepare_button = primary_button(
        "Prepare cloud",
        icon="cloud",
    )

    actions = toolbar(
        test_button,
        prepare_button,
        gap="8px",
    )

    # ---------------------------------------------------------
    # Advanced infrastructure configuration
    # ---------------------------------------------------------

    profile_widget = W.Text(
        description="Profile:",
        value=profile,
        placeholder="Optional AWS profile",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "110px",
        },
    )

    s3_prefix_widget = W.Text(
        description="S3 bucket:",
        value=s3_prefix,
        placeholder="cryostack-runs-<account-id>  (or s3://<bucket>)",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "110px",
        },
    )

    job_queue_widget = W.Text(
        description="Queue:",
        value=job_queue,
        placeholder="AWS Batch job queue",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "110px",
        },
    )

    job_definition_widget = W.Text(
        description="Job definition:",
        value=job_definition,
        placeholder="job-definition[:revision]",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "110px",
        },
    )

    job_name_widget = W.Text(
        description="Job name:",
        value=job_name,
        placeholder="icesheets",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "110px",
        },
    )

    advanced_caption = W.HTML(
        value=(
            "<div style='font-size:11px;color:#96a1b4;line-height:1.45;'>"
            "<b>Leave these fields blank</b> to use the CryoStack-prepared "
            "resources for the connected AWS account (bucket, queue and job "
            "definition are derived automatically). Set a field only to "
            "override that specific resource."
            "</div>"
        ),
    )

    matlab_license_arn_widget = W.Text(
        description="MATLAB license ARN:",
        value=matlab_license_secret_arn,
        placeholder="arn:aws:secretsmanager:<region>:<account>:secret:<name>",
        layout=W.Layout(
            width="100%",
        ),
        style={
            "description_width": "150px",
        },
    )

    matlab_license_caption = W.HTML(
        value=(
            "<div style='font-size:11px;color:#96a1b4;line-height:1.45;'>"
            "ISSM cloud runs need a MATLAB license reachable from AWS Batch. "
            "Create a Secrets Manager secret <b>in your own AWS account</b> "
            "holding the license value, then paste its ARN here -- CryoStack "
            "never sees or stores the license value itself, only this "
            "non-secret identifier."
            "</div>"
        ),
    )

    matlab_license_save_button = secondary_button(
        "Save license ARN",
        icon="save",
    )

    advanced_body = W.VBox(
        [
            advanced_caption,
            profile_widget,
            s3_prefix_widget,
            job_queue_widget,
            job_definition_widget,
            job_name_widget,
            matlab_license_caption,
            matlab_license_arn_widget,
            matlab_license_save_button,
        ],
        layout=W.Layout(
            width="100%",
            gap="5px",
            padding="6px 0",
        ),
    )

    advanced = W.Accordion(
        children=[
            advanced_body,
        ],
        selected_index=None,
        layout=W.Layout(
            width="100%",
        ),
    )

    advanced.set_title(
        0,
        "Advanced cloud settings",
    )

    # ---------------------------------------------------------
    # Card
    # ---------------------------------------------------------

    heading = W.HTML(
        value="""
        <div style="margin-bottom:4px;">
          <div
            style="
              font-size:13px;
              font-weight:700;
              color:#172033;
            "
          >
            Cloud Environment
          </div>

          <div
            style="
              margin-top:3px;
              font-size:11px;
              color:#66758d;
              line-height:1.45;
            "
          >
            Connect your cloud account and let CryoStack prepare the
            resources required for this experiment.
          </div>
        </div>
        """
    )

    aws_account = _build_aws_account_section()
    run_estimate = _build_run_estimate_section()
    active_run = _build_active_run_section()

    infra_heading = W.HTML(
        value=(
            "<div style='font-size:12px;font-weight:700;color:#172033;"
            "letter-spacing:.02em;margin-top:2px;'>INFRASTRUCTURE</div>"
        ),
    )

    body = W.VBox(
        [
            heading,
            provider_widget,
            region_widget,
            aws_account["aws_account_section"],
            infra_heading,
            status_panel,
            actions,
            run_estimate["run_estimate_section"],
            run_estimate["review_panel"],
            active_run["active_run_section"],
            advanced,
        ],
        layout=W.Layout(
            width="100%",
            gap="7px",
        ),
    )

    container = W.VBox(
        [
            body,
        ],
        layout=W.Layout(
            width="100%",
            border="1px solid #dfe6ef",
            padding="12px",
        ),
    )

    return CloudEnvironmentWidgets(
        provider=provider_widget,
        region=region_widget,
        profile=profile_widget,

        s3_prefix=s3_prefix_widget,
        job_queue=job_queue_widget,
        job_definition=job_definition_widget,
        job_name=job_name_widget,
        matlab_license_arn=matlab_license_arn_widget,
        matlab_license_save_button=matlab_license_save_button,

        account_status=account_status,
        storage_status=storage_status,
        registry_status=registry_status,
        compute_status=compute_status,

        test_button=test_button,
        prepare_button=prepare_button,

        advanced=advanced,

        container=container,

        aws_account_section=aws_account["aws_account_section"],
        aws_account_status=aws_account["aws_account_status"],
        aws_account_detail=aws_account["aws_account_detail"],
        connect_button=aws_account["connect_button"],
        connect_form=aws_account["connect_form"],
        connect_actions=aws_account["connect_actions"],
        open_setup_link=aws_account["open_setup_link"],
        role_arn_input=aws_account["role_arn_input"],
        verify_button=aws_account["verify_button"],
        recheck_button=aws_account["recheck_button"],
        disconnect_button=aws_account["disconnect_button"],
        recovery_actions=aws_account["recovery_actions"],
        retry_button=aws_account["retry_button"],
        change_account_button=aws_account["change_account_button"],
        change_account_panel=aws_account["change_account_panel"],
        change_account_notice=aws_account["change_account_notice"],
        change_account_status=aws_account["change_account_status"],
        change_setup_link=aws_account["change_setup_link"],
        change_role_arn_input=aws_account["change_role_arn_input"],
        change_verify_button=aws_account["change_verify_button"],
        change_cancel_button=aws_account["change_cancel_button"],

        run_estimate_section=run_estimate["run_estimate_section"],
        run_estimate_line=run_estimate["run_estimate_line"],
        review_button=run_estimate["review_button"],
        review_panel=run_estimate["review_panel"],
        review_body=run_estimate["review_body"],
        review_notice=run_estimate["review_notice"],
        review_back_button=run_estimate["review_back_button"],
        launch_button=run_estimate["launch_button"],

        active_run_section=active_run["active_run_section"],
        active_run_title=active_run["active_run_title"],
        active_run_status=active_run["active_run_status"],
        active_run_detail=active_run["active_run_detail"],
        active_run_diagnostics=active_run["active_run_diagnostics"],
        active_run_actions=active_run["active_run_actions"],
        active_run_log_button=active_run["active_run_log_button"],
        active_run_results_button=active_run["active_run_results_button"],
        active_run_terminate_button=active_run["active_run_terminate_button"],
    )