# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Account Connection
# File        : onboarding.py
#
# Description :
#     UI-neutral orchestration of the "Connect AWS Account" flow: mint /
#     reuse the connection, build the Quick Create URL, verify, disconnect.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-09-03
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
:class:`AWSOnboarding` -- the single object a frontend talks to.

It owns no widgets and no AWS semantics of its own; it composes the connection
store, the deployment principal, the CloudFormation template URL, and
:func:`verify_connection`. Every method returns plain data safe to render.

Key behaviours the UI relies on:

* ``begin()`` **reuses** the existing connection record -- the ExternalId is
  *not* regenerated on a page refresh. Only an explicit :meth:`disconnect`
  (or :meth:`reconnect`) rotates it.
* :meth:`verify` always persists a record that is safe to store (no STS
  credentials); it returns the live context for immediate use only.

**Change AWS account is staged, not destructive.** ``begin_change_account()``
mints a brand-new connection (fresh ExternalId) into a SEPARATE pending slot
without touching the active connection. ``verify_pending_replacement()`` is
the only path that can overwrite the active connection, and only when the
pending one has ITSELF passed AssumeRole + GetCallerIdentity --
:meth:`AWSConnectionStore.promote_pending`. A failed verification, a page
refresh, or the user simply never coming back leaves the active connection
(its Role ARN and ExternalId) exactly as it was. See
``cloud_connect_runtime.py`` for the Retry / Cancel / Back-to-current-account
UI this enables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryostack_src.workspace.identity import WorkspaceUser

from .cloudformation import connection_stack_name, quick_create_url
from .defaults import derive_cloud_defaults
from .models import AWSConnection
from .principal import cryostack_principal_arn
from .store import AWSConnectionStore
from .verify import VerificationResult, verify_connection

#: deployment env var: public URL the CryoStackExecutionRole template is hosted at
TEMPLATE_URL_ENV = "CRYOSTACK_CF_TEMPLATE_URL"
DEFAULT_REGION = "us-east-2"


class OnboardingConfigError(RuntimeError):
    """A required deployment setting for onboarding is missing."""


@dataclass
class ConnectStep:
    """What the UI needs to render the 3-step Connect card."""

    connection: AWSConnection
    setup_url: str
    stack_name: str
    principal_arn: str
    external_id: str


class AWSOnboarding:
    def __init__(
        self,
        *,
        user: WorkspaceUser | None = None,
        workspace_root=None,
        require_authenticated: bool = True,
        template_url: str | None = None,
        region: str = DEFAULT_REGION,
        principal_arn: str | None = None,
        runner=None,
    ) -> None:
        self.store = AWSConnectionStore(
            user=user,
            workspace_root=workspace_root,
            require_authenticated=require_authenticated,
        )
        self.region = (region or DEFAULT_REGION).strip()
        self._template_url = template_url
        self._principal_arn = principal_arn
        self._runner = runner

    # -- config (fail clearly) --------------------------------------
    def principal_arn(self) -> str:
        return self._principal_arn or cryostack_principal_arn()

    def template_url(self) -> str:
        url = self._template_url or (os.environ.get(TEMPLATE_URL_ENV) or "").strip()
        if not url:
            raise OnboardingConfigError(
                "The CryoStack access-role template URL is not configured on "
                f"this deployment. Set {TEMPLATE_URL_ENV}."
            )
        return url

    # -- read ------------------------------------------------------
    def current(self) -> AWSConnection | None:
        return self.store.load()

    def summary(self) -> dict:
        """A render-ready snapshot for the Cloud panel (no secrets)."""
        conn = self.store.load()
        if conn is None:
            return {"status": "disconnected", "region": self.region}
        out = conn.to_public_dict(own=True)
        out["status"] = "connected" if conn.is_connected else conn.status
        if conn.is_connected:
            out["defaults"] = derive_cloud_defaults(
                account_id=conn.account_id, region=conn.region
            ).as_dict()
            out["access"] = "Temporary role"
        return out

    # -- connect flow --------------------------------------------
    def _connect_step(self, conn: AWSConnection) -> ConnectStep:
        """Build the Quick Create URL/ConnectStep for ``conn`` as it stands
        right now -- the ONE place stack-name derivation happens, so every
        caller (begin/begin_change_account/the two retry_* methods) agrees.
        Never mutates or persists ``conn``; callers do that themselves."""
        principal = self.principal_arn()          # raise early if unset
        template_url = self.template_url()
        stack_name = connection_stack_name(conn.connection_id, attempt=conn.stack_attempt)
        url = quick_create_url(
            template_url=template_url,
            external_id=conn.external_id,
            region=conn.region,
            principal_arn=principal,
            stack_name=stack_name,
        )
        return ConnectStep(
            connection=conn,
            setup_url=url,
            stack_name=stack_name,
            principal_arn=principal,
            external_id=conn.external_id,
        )

    def begin(self, *, region: str | None = None) -> ConnectStep:
        """Load or mint this user's connection and build the Quick Create URL.

        Reuses an existing record (stable ExternalId, stable stack name/
        attempt). A region is only applied to a *new* record.
        """
        conn = self.store.load()
        if conn is None:
            conn = self.store.create(region=(region or self.region).strip())
        return self._connect_step(conn)

    def retry_with_fresh_stack(self) -> ConnectStep:
        """The ACTIVE connection's previous CloudFormation attempt rolled
        back (e.g. ``ROLLBACK_COMPLETE``) and its stack name can't be
        reused. Mint a fresh, non-colliding stack name for the SAME
        connection -- ExternalId and any already-recorded role/status are
        completely untouched -- and return a new Quick Create URL for it.
        Never call this for an ordinary retry (a page reload, or "I created
        the role, verify it now"): :meth:`begin` already reuses the same
        stack name for those, on purpose, so a stack that DID complete
        keeps being reusable/inspectable under the same name."""
        conn = self.store.load()
        if conn is None:
            raise OnboardingConfigError(
                "No AWS connection to retry. Click Connect AWS account first."
            )
        conn = self.store.save(conn.with_new_stack_attempt())
        return self._connect_step(conn)

    def reconnect(self, *, region: str | None = None) -> ConnectStep:
        """Explicitly rotate: new connection record + new ExternalId.

        Immediate and destructive -- the active connection is replaced right
        away, before anything has verified. Kept for callers that genuinely
        want that (e.g. tests exercising the primitive in isolation). The
        "Change AWS account" UI action does NOT call this any more -- see
        :meth:`begin_change_account` / :meth:`verify_pending_replacement`.
        """
        self.store.delete()
        self.store.create(region=(region or self.region).strip())
        return self.begin(region=region)

    # -- Change AWS account: staged, non-destructive ----------------------
    def has_pending_replacement(self) -> bool:
        return self.store.load_pending() is not None

    def pending_replacement_summary(self) -> dict | None:
        """A render-ready snapshot of the staged replacement attempt, or
        ``None`` when there isn't one. Never ``"connected"`` -- a pending
        replacement that verifies is promoted to active in the same call
        that verifies it, so a summary is only ever read back as
        ``pending``/``error``."""
        conn = self.store.load_pending()
        if conn is None:
            return None
        out = conn.to_public_dict(own=True)
        out["status"] = conn.status
        return out

    def begin_change_account(self, *, region: str | None = None) -> ConnectStep:
        """Start (or resume) a STAGED replacement AWS-account connection.

        Mints a fresh ExternalId into the pending slot ONLY on the first
        call; a page reload or a repeat click reuses the existing pending
        record (same "reuse, never silently rotate" rule ``begin()``
        follows for the active connection) so a role already created
        against it keeps working. The ACTIVE connection is never read or
        modified by this call -- it stays exactly as it was until
        :meth:`verify_pending_replacement` succeeds.
        """
        pending = self.store.load_pending()
        if pending is None:
            pending = self.store.create_pending(region=(region or self.region).strip())
        return self._connect_step(pending)

    def retry_pending_with_fresh_stack(self) -> ConnectStep:
        """Same escape hatch as :meth:`retry_with_fresh_stack`, for a STAGED
        "Change AWS account" replacement whose CloudFormation attempt rolled
        back. The active connection is never read or touched by this call."""
        pending = self.store.load_pending()
        if pending is None:
            raise OnboardingConfigError(
                "No pending AWS account switch to retry. Click Change AWS "
                "account first."
            )
        pending = self.store.save_pending(pending.with_new_stack_attempt())
        return self._connect_step(pending)

    def verify_pending_replacement(self, *, role_arn: str) -> VerificationResult:
        """Assume the role for the STAGED replacement.

        * On success: the pending connection is atomically PROMOTED to
          become the active connection (:meth:`AWSConnectionStore.
          promote_pending`) and the pending slot is cleared. This is the
          ONLY moment the active connection changes.
        * On failure: only the pending record is updated (role ARN +
          error reason) -- the active connection is untouched, so Retry
          connection on it (the ORIGINAL account) keeps working exactly as
          before.

        Returns the pending connection's own :class:`VerificationResult` in
        both cases (its ``.connection`` reflects the STAGED attempt, not
        necessarily what is active afterwards -- callers that need the new
        active state should re-read :meth:`summary`).
        """
        pending = self.store.load_pending()
        if pending is None:
            raise OnboardingConfigError(
                "No pending AWS account switch to verify. Click Change AWS "
                "account first."
            )
        result = verify_connection(pending, role_arn=role_arn, runner=self._runner)
        self.store.save_pending(result.connection)
        if result.ok:
            self.store.promote_pending()
        return result

    def cancel_change_account(self) -> None:
        """Abandon the staged replacement attempt -- "Cancel / Back to
        current account". The active connection (if any) is completely
        untouched; nothing was ever sent to AWS by this call or by
        :meth:`begin_change_account` itself (only the eventual Verify
        click calls AssumeRole)."""
        self.store.delete_pending()

    def verify(self, *, role_arn: str) -> VerificationResult:
        """Assume the role, confirm identity, persist the (non-secret) result."""
        conn = self.store.load()
        if conn is None:
            conn = self.store.create(region=self.region)
        result = verify_connection(conn, role_arn=role_arn, runner=self._runner)
        self.store.save(result.connection)
        return result

    def recheck(self) -> VerificationResult:
        """Re-verify an already-connected account with its stored role ARN."""
        conn = self.store.load()
        if conn is None or not conn.role_arn:
            raise OnboardingConfigError("No AWS connection to re-check.")
        result = verify_connection(conn, runner=self._runner)
        self.store.save(result.connection)
        return result

    def disconnect(self) -> None:
        """Remove this user's connection metadata. Nothing to revoke -- STS
        credentials are short-lived and were never stored."""
        self.store.delete()
