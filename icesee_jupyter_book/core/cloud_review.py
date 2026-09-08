"""ICESEE DA-aware Cloud Review & Launch content.

Reuses the SAME shared Cloud Environment review shell CryoLauncher's own
Review & Launch uses (``build_cloud_environment_card()``'s
``review_panel``/``review_body``/``review_notice``/``launch_button``/
``review_back_button``/``run_estimate_section`` -- built once, shared
verbatim), but never CryoLauncher's own ``cryostack_src.cloud.review``
module: that schema is model/example/run_target-shaped (a single staged
script), and ``SUPPORTED_CLOUD_MODELS`` does not include ``"icesee"`` --
forcing ICESEE through it would either flatten the DA identity or require
editing a shared module's truth-claims about what CryoStack's generic cloud
runner actually supports. This module is the same SHAPE (an immutable
review + a launch gate + a drift digest) with ICESEE's own DA-shaped
fields instead.

:func:`icesee_cloud_runtime_ready` is a real, checkable fact (whether a
tested cloud container/job definition is registered for "icesee" in
``cryostack_src.models.stack.images``) -- not a placeholder. It is false
today (see ``overnight/AUDIT_icesee_cloud_execution_parity.md``), so Launch
is honestly blocked until a real one is registered, regardless of how
ready the generic AWS account/storage/compute infrastructure is.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from cryostack_src.cloud.review import InfrastructureReadiness


def icesee_cloud_runtime_ready() -> bool:
    """Whether ICESEE has a registered tested cloud container image (and,
    by implication, a Batch job definition CryoStack can point at it)."""
    from cryostack_src.models.stack import default_tested_image_for_model

    return default_tested_image_for_model("icesee") is not None


@dataclass
class IceseeCloudReview:
    # experiment (DA-shaped -- forecast model / filter / ensemble, not a
    # staged model/example/run.py script)
    forecast_model: str
    filter_alg: str
    ensemble_size: int
    # execution
    execution_mode: str
    compute_backend: str
    parallel_processes: int
    # aws (non-secret)
    account_id: str
    region: str
    # container image -- empty until a real tested ICESEE image exists
    image_label: str = ""
    image_reference: str = ""
    image_digest: str = ""
    image_public_url: str = ""
    # infrastructure
    infrastructure: InfrastructureReadiness = field(default_factory=InfrastructureReadiness)
    icesee_runtime_ready: bool = False
    # gating
    can_launch: bool = False
    blocked_reasons: list = field(default_factory=list)
    # drift protection
    digest: str = ""

    def to_public_dict(self) -> dict:
        return {
            "forecast_model": self.forecast_model,
            "filter": self.filter_alg,
            "ensemble_size": self.ensemble_size,
            "execution_mode": self.execution_mode,
            "compute_backend": self.compute_backend,
            "parallel_processes": self.parallel_processes,
            "account_id": self.account_id,
            "region": self.region,
            "image_reference": self.image_reference,
            "image_digest": self.image_digest,
            "infrastructure": self.infrastructure.as_dict(),
            "icesee_runtime_ready": self.icesee_runtime_ready,
            "can_launch": self.can_launch,
            "blocked_reasons": list(self.blocked_reasons),
            "digest": self.digest,
        }


def icesee_review_digest(
    *, forecast_model: str, filter_alg: str, ensemble_size: int,
    parallel_processes: int, region: str, account_id: str,
) -> str:
    """A short stable hash over the billable/scientific config -- the same
    drift-detection idea as CryoLauncher's ``review_digest``: any change
    invalidates an open review and forces Review again before Launch."""
    payload = {
        "forecast_model": (forecast_model or "").strip().lower(),
        "filter": (filter_alg or "").strip().lower(),
        "ensemble_size": int(ensemble_size or 0),
        "parallel_processes": int(parallel_processes or 0),
        "region": region, "account_id": account_id,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def build_icesee_cloud_review(
    *,
    forecast_model: str,
    filter_alg: str,
    ensemble_size: int,
    parallel_processes: int,
    account_id: str,
    region: str,
    infrastructure: InfrastructureReadiness,
    account_freshly_verified: bool,
) -> IceseeCloudReview:
    """Assemble an ICESEE cloud review and decide whether Launch is
    allowed. Launch is gated on: fresh account verification + storage/
    compute infrastructure Ready + a registered ICESEE tested runtime --
    never faked, never inherited from CryoLauncher's own model gate."""
    reasons: list[str] = []

    if not account_freshly_verified:
        reasons.append(
            "Your AWS account connection could not be verified just now. "
            "Re-check it in Cloud Environment → AWS ACCOUNT."
        )
    for label, ready in (
        ("Storage", infrastructure.storage),
        ("Compute (AWS Batch)", infrastructure.compute),
    ):
        if not ready:
            reasons.append(f"{label} is not prepared. Run Prepare cloud first.")

    runtime_ready = icesee_cloud_runtime_ready()
    image_label = image_reference = image_digest = image_public_url = ""
    if runtime_ready:
        from cryostack_src.models.stack import default_tested_image_for_model

        img = default_tested_image_for_model("icesee")
        if img is not None:
            image_label, image_reference = img.label, img.reference
            image_digest = img.digest
            image_public_url = img.public_url or ""
    else:
        reasons.append(
            "ICESEE has no tested cloud container image or Batch job "
            "definition registered yet -- this is a real infrastructure "
            "gap, not a temporary check."
        )

    digest = icesee_review_digest(
        forecast_model=forecast_model, filter_alg=filter_alg,
        ensemble_size=ensemble_size, parallel_processes=parallel_processes,
        region=region, account_id=account_id,
    )

    return IceseeCloudReview(
        forecast_model=forecast_model, filter_alg=filter_alg,
        ensemble_size=ensemble_size, execution_mode="cloud",
        compute_backend="AWS Batch (Fargate)",
        parallel_processes=parallel_processes,
        account_id=account_id, region=region,
        image_label=image_label, image_reference=image_reference,
        image_digest=image_digest, image_public_url=image_public_url,
        infrastructure=infrastructure, icesee_runtime_ready=runtime_ready,
        can_launch=not reasons, blocked_reasons=reasons, digest=digest,
    )


def render_icesee_review_panel(widgets, review: IceseeCloudReview) -> None:
    """Write the ICESEE DA-aware review body into the SAME shared
    review_body/launch_button widgets ``build_cloud_environment_card()``
    already provides -- reusing the shell, never
    ``cryostack_src.frontend.cryolauncher.cloud_environment.set_review_panel``
    (which is model/example/run_target-shaped and must keep rendering
    CryoLauncher's own reviews unchanged)."""
    from cryostack_src.frontend.cryolauncher.cloud_environment import escape_text

    infra = review.infrastructure

    def _yn(ready: bool) -> str:
        color = "#2f8f4e" if ready else "#b23c3c"
        return f"<span style='color:{color};'>{'Ready' if ready else 'Not ready'}</span>"

    blocked = ""
    if not review.can_launch:
        items = "".join(f"<li>{escape_text(x)}</li>" for x in review.blocked_reasons)
        blocked = (
            "<div style='font-size:11px;color:#b23c3c;background:#fdf1f1;"
            "border:1px solid #f0d5d5;border-radius:6px;padding:8px;margin-top:6px;'>"
            f"<b>Launch is blocked:</b><ul style='margin:4px 0 0 16px;padding:0;'>{items}</ul>"
            "</div>"
        )

    if review.image_reference:
        ref_html = (
            f"<a href='{escape_text(review.image_public_url)}' target='_blank' "
            f"rel='noopener noreferrer'>{escape_text(review.image_reference)}</a>"
            if review.image_public_url else escape_text(review.image_reference)
        )
        short_digest = (
            review.image_digest[:22] + "…"
            if review.image_digest.startswith("sha256:") else review.image_digest
        )
        image_rows = (
            '<tr><td colspan="2" style="padding-top:6px;font-weight:700;color:#172033;">'
            'Container image</td></tr>'
            f'<tr><td style="padding:1px 12px 1px 0;">Image</td><td>{ref_html} '
            '<span style="color:#96a1b4;">· Tested</span></td></tr>'
            f'<tr><td style="padding:1px 12px 1px 0;">Digest</td>'
            f'<td><code style="font-size:10px;">{escape_text(short_digest) or "—"}</code></td></tr>'
        )
    else:
        image_rows = (
            '<tr><td colspan="2" style="padding-top:6px;font-weight:700;color:#172033;">'
            'Container image</td></tr>'
            '<tr><td colspan="2" style="color:#b23c3c;">No tested ICESEE cloud image '
            'registered yet</td></tr>'
        )

    widgets.review_body.value = f"""
      <table style="font-size:11px;color:#66758d;border-collapse:collapse;width:100%;">
        <tr><td colspan="2" style="padding-top:4px;font-weight:700;color:#172033;">Experiment</td></tr>
        <tr><td style="padding:1px 12px 1px 0;width:140px;">Application</td><td>ICESEE</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Forecast model</td><td>{escape_text(review.forecast_model or "—")}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Filter</td><td>{escape_text(review.filter_alg or "—")}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Ensemble size</td><td>{review.ensemble_size}</td></tr>
        <tr><td colspan="2" style="padding-top:6px;font-weight:700;color:#172033;">Execution</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Mode</td><td>Cloud</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Backend</td><td>{escape_text(review.compute_backend)}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Parallel processes</td><td>{review.parallel_processes}</td></tr>
        {image_rows}
        <tr><td colspan="2" style="padding-top:6px;font-weight:700;color:#172033;">AWS</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Account</td><td><code>{escape_text(review.account_id or "—")}</code></td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Region</td><td>{escape_text(review.region)}</td></tr>
        <tr><td colspan="2" style="padding-top:6px;font-weight:700;color:#172033;">Infrastructure</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Account</td><td>{_yn(infra.account)}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Storage</td><td>{_yn(infra.storage)}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Container</td><td>{_yn(review.icesee_runtime_ready)}</td></tr>
        <tr><td style="padding:1px 12px 1px 0;">Compute</td><td>{_yn(infra.compute)}</td></tr>
      </table>
      {blocked}
    """
    widgets.launch_button.disabled = not review.can_launch
