"""ApprovalRequest — kryptografisk approval-binding for connector tool calls.

When PermissionEngine classifies a tool as WRITE/CONFIRM/DANGEROUS, the
connector creates an ApprovalRequest and returns 202 Accepted. The user
signs (approved/denied) via the dashboard, and the connector verifies the
signature before executing the original intent.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ApprovalRequest(BaseModel):
    """Cryptographic approval binding for a dangerous tool call.

    The user signs canonical_string(intent_id || tool_name || args_hash ||
    risk_level || decision || nonce) with their HMAC user_secret. The
    connector verifies this signature before executing the original intent.
    """

    schema_version: int = 1
    approval_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    intent_id: str
    tool_name: str
    args_hash: str = ""
    risk_level: str  # write | confirm | dangerous
    workspace_id: str = ""
    connector_id: str = ""
    user_decision: str = "pending"  # pending | approved | denied | timeout
    user_signature: str = ""
    nonce: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    approved_at: str = ""
    expires_at: str = ""
    intent_payload: dict[str, Any] = Field(default_factory=dict)

    def canonical_signing_string(self) -> str:
        """Deterministic string for user HMAC signing.

        Uses pipe (|) as delimiter. This is what the user signs in the
        dashboard before sending back to the connector.
        """
        parts = [
            str(self.schema_version),
            self.approval_id,
            self.intent_id,
            self.tool_name,
            self.args_hash,
            self.risk_level,
            self.user_decision,
            self.nonce,
        ]
        return "|".join(parts)

    def is_expired(self, timeout_s: int = 300) -> bool:
        """Check if this approval request has timed out."""
        if self.user_decision != "pending":
            return False
        try:
            dt = datetime.fromisoformat(self.created_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            return (now - dt).total_seconds() > timeout_s
        except (ValueError, TypeError):
            return False

    def model_dump_api(self) -> dict[str, Any]:
        """Serialise for API responses (no intent_payload by default)."""
        return {
            "approval_id": self.approval_id,
            "intent_id": self.intent_id,
            "tool_name": self.tool_name,
            "args_hash": self.args_hash,
            "risk_level": self.risk_level,
            "workspace_id": self.workspace_id,
            "connector_id": self.connector_id,
            "user_decision": self.user_decision,
            "nonce": self.nonce,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "expires_at": self.expires_at,
        }


class ApprovalResolveRequest(BaseModel):
    """Payload sent by the dashboard when user makes a decision."""

    approval_id: str
    user_decision: str  # approved | denied
    user_signature: str = ""


def canonical_approval_bytes(approval: ApprovalRequest) -> bytes:
    """Canonical UTF-8 bytes for HMAC signing by the user."""
    return approval.canonical_signing_string().encode("utf-8")


def verify_approval_signature(
    approval: ApprovalRequest,
    user_secret: str,
) -> bool:
    """Verify the user's HMAC-SHA256 signature over the approval.

    The user signs: canonical(intent_id + tool_name + args_hash + risk_level
    + user_decision + nonce) using their user_secret.
    """
    import hashlib
    import hmac

    expected = hmac.new(
        user_secret.encode("utf-8"),
        canonical_approval_bytes(approval),
        hashlib.sha256,
    ).hexdigest()

    if not approval.user_signature:
        return False

    import hmac as hmac_mod

    return hmac_mod.compare_digest(approval.user_signature, expected)
