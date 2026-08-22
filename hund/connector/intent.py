"""Intent schema — signed request envelope between cloud and connector."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class IntentRequest(BaseModel):
    """Signed intent from cloud to connector. Validated locally before exec."""

    schema_version: int = 1
    intent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    org_id: str = ""
    workspace_id: str
    connector_id: str
    run_id: str = ""
    session_id: str = ""
    intent_type: str  # tool_call | event_stream | health_check
    tool_name: str | None = None
    args_redacted: dict[str, Any] = Field(default_factory=dict)
    args_hash: str = ""
    risk_hint: str = "safe"
    policy_version: str = ""
    nonce: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    expires_at: str = ""
    actor: str = "connector"
    signature: str = ""

    @field_validator("intent_type")
    @classmethod
    def _valid_intent_type(cls, v: str) -> str:
        if v not in {"tool_call", "event_stream", "health_check"}:
            raise ValueError(f"invalid intent_type: {v}")
        return v

    @field_validator("risk_hint")
    @classmethod
    def _valid_risk_hint(cls, v: str) -> str:
        if v not in {"safe", "confirm", "dangerous"}:
            raise ValueError(f"invalid risk_hint: {v}")
        return v

    def canonical_signing_string(self) -> str:
        """Deterministic string for HMAC signing. Excludes signature field.

        Uses pipe (|) as delimiter because timestamps and UUIDs can contain
        colons and dashes.
        """
        parts = [
            str(self.schema_version),
            self.intent_id,
            self.org_id,
            self.workspace_id,
            self.connector_id,
            self.run_id,
            self.session_id,
            self.intent_type,
            self.tool_name or "",
            self.args_hash,
            self.nonce,
            self.timestamp,
            self.expires_at,
            self.actor,
        ]
        return "|".join(parts)


class IntentResponse(BaseModel):
    """Response from connector back to cloud."""

    intent_id: str
    status: str  # ok | denied | blocked | error
    risk: str = "none"
    reason: str = ""
    result_redacted: str | None = None
    trace_event_id: str | None = None
