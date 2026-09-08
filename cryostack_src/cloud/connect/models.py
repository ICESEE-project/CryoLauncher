# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Account Connection
# File        : models.py
#
# Description :
#     The non-secret AWS account connection record persisted per CryoStack
#     user.
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
The persisted AWS connection record.

Every field here is *non-secret* connection metadata. There is deliberately
no place to put an access key or a session token: the temporary credentials
from :func:`assume_role` live in an :class:`AWSExecutionContext`, which is
never serialised.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone

# connection lifecycle
STATUS_PENDING = "pending"        # record minted, role not yet created/verified
STATUS_CONNECTED = "connected"    # AssumeRole + GetCallerIdentity succeeded
STATUS_ERROR = "error"            # last verification attempt failed

_ROLE_ARN_RE = re.compile(
    r"\Aarn:aws[a-z-]*:iam::(?P<account>\d{12}):role/(?P<name>[\w+=,.@/-]+)\Z"
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def account_id_from_role_arn(role_arn: str) -> str:
    """Return the 12-digit account id embedded in an IAM role ARN, or ``""``."""
    match = _ROLE_ARN_RE.match((role_arn or "").strip())
    return match.group("account") if match else ""


def is_valid_role_arn(role_arn: str) -> bool:
    return bool(_ROLE_ARN_RE.match((role_arn or "").strip()))


@dataclass
class AWSConnection:
    """A CryoStack user's connection to one AWS account.

    Persisted as JSON by :class:`AWSConnectionStore`. No secret fields.
    """

    connection_id: str
    external_id: str
    region: str
    provider: str = "aws"
    role_arn: str = ""
    account_id: str = ""
    status: str = STATUS_PENDING
    status_reason: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    verified_at: str = ""
    #: NON-SECRET: an AWS Secrets Manager secret ARN in the user's OWN account
    #: whose value is the ISSM MATLAB license (``MLM_LICENSE_FILE``, a
    #: ``<port>@<host>`` string). CryoStack stores only the ARN; the value
    #: never touches CryoStack, git, the image, S3, manifests, logs, or a
    #: command preview -- AWS Batch injects it into the container at launch
    #: (containerProperties.secrets). Empty = ISSM cloud runtime not
    #: configured. See cryostack_src/cloud/matlab_license.py.
    matlab_license_secret_arn: str = ""
    #: which CloudFormation stack NAME this connection's Quick Create URL
    #: currently points at, scoped by cloudformation.connection_stack_name()
    #: to (connection_id, stack_attempt) -- never a fixed name, so a second
    #: connection can never collide with this one's stack. Starts at 1 and
    #: is bumped ONLY by with_new_stack_attempt(), the explicit "my previous
    #: stack rolled back, give me a fresh non-colliding name" escape hatch --
    #: never on an ordinary retry, and never touching external_id/role_arn.
    stack_attempt: int = 1

    # -- derived -----------------------------------------------------------
    @property
    def is_connected(self) -> bool:
        return self.status == STATUS_CONNECTED and bool(self.account_id)

    @property
    def role_account_id(self) -> str:
        return account_id_from_role_arn(self.role_arn)

    # -- transitions (return a new record; never mutate in place) ---------
    def with_role(self, role_arn: str) -> "AWSConnection":
        return replace(self, role_arn=(role_arn or "").strip())

    def with_matlab_license_secret(self, secret_arn: str) -> "AWSConnection":
        """Record the (non-secret) Secrets Manager ARN for the ISSM MATLAB
        license. ``""`` clears it. The secret VALUE is never handled here."""
        return replace(self, matlab_license_secret_arn=(secret_arn or "").strip())

    def with_new_stack_attempt(self) -> "AWSConnection":
        """Mint a fresh, non-colliding CloudFormation stack name for THIS
        SAME connection (e.g. the previous stack rolled back to
        ROLLBACK_COMPLETE) -- external_id, role_arn and status are
        completely untouched, so an already-verified role keeps working and
        an in-progress ExternalId trust relationship is not invalidated."""
        return replace(self, stack_attempt=self.stack_attempt + 1)

    def mark_connected(self, *, account_id: str) -> "AWSConnection":
        return replace(
            self,
            account_id=account_id,
            status=STATUS_CONNECTED,
            status_reason="",
            verified_at=utc_now_iso(),
        )

    def mark_error(self, reason: str) -> "AWSConnection":
        return replace(
            self,
            status=STATUS_ERROR,
            status_reason=(reason or "").strip()[:500],
            verified_at=utc_now_iso(),
        )

    # -- serialisation ---------------------------------------------------
    def to_dict(self) -> dict:
        """The full record (all fields are non-secret)."""
        return asdict(self)

    def to_public_dict(self, *, own: bool) -> dict:
        """A view safe to hand to a frontend.

        ``own=False`` (some other user's connection -- should never normally
        happen) strips everything that could aid impersonation.
        """
        base = {
            "provider": self.provider,
            "region": self.region,
            "account_id": self.account_id,
            "status": self.status,
            "is_connected": self.is_connected,
            "verified_at": self.verified_at,
        }
        if not own:
            return {"provider": self.provider, "status": "unknown"}
        base.update(
            {
                "connection_id": self.connection_id,
                "role_arn": self.role_arn,
                "external_id": self.external_id,
                "status_reason": self.status_reason,
                "created_at": self.created_at,
                # non-secret ARN only (the license value lives in the user's
                # own Secrets Manager and never reaches CryoStack)
                "matlab_license_secret_arn": self.matlab_license_secret_arn,
                "stack_attempt": self.stack_attempt,
            }
        )
        return base

    @classmethod
    def from_dict(cls, data: dict) -> "AWSConnection":
        allowed = {f for f in cls.__dataclass_fields__}  # noqa: C416
        return cls(**{k: v for k, v in (data or {}).items() if k in allowed})
