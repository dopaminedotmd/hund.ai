"""Typed contracts for tool execution, results, and context."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ..learning.redactor import redact_text

_SENSITIVE_PARAM_PATTERN = re.compile(
    r"(?i)^(token|access_token|key|api_key|api-key|secret|password|auth|authorization|cookie|sig|signature)$"
)


def sanitize_url_for_citation(url: str) -> str:
    """Sanitize a URL for safe public rendering / LLM citation.

    Strips userinfo (user:pass@) and query parameters containing sensitive tokens.
    """
    if not url or not isinstance(url, str):
        return ""
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return ""
        netloc = parsed.netloc
        if "@" in netloc:
            netloc = netloc.split("@", 1)[1]

        query_tuples = parse_qsl(parsed.query, keep_blank_values=True)
        safe_query = [
            (k, v) for k, v in query_tuples
            if not _SENSITIVE_PARAM_PATTERN.match(k)
        ]
        new_query = urlencode(safe_query)

        fragment = parsed.fragment
        if fragment:
            fragment = redact_text(fragment).text
            if "[REDACTED" in fragment:
                fragment = ""

        reconstructed = urlunparse((
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            new_query,
            fragment,
        ))
        return redact_text(reconstructed).text
    except Exception:
        return redact_text(url).text


_UNSUPPORTED = object()


def _sanitize_json_value(value: Any, *, provenance: bool = False, key: str = "") -> Any:
    """Return a detached JSON-native value without invoking arbitrary __str__."""
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str):
            if provenance and key.casefold() == "url":
                return sanitize_url_for_citation(value)
            return redact_text(value).text
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _UNSUPPORTED
    if isinstance(value, (list, tuple)):
        clean_items: list[Any] = []
        for item in value:
            clean = _sanitize_json_value(item, provenance=provenance)
            if clean is _UNSUPPORTED:
                return _UNSUPPORTED
            clean_items.append(clean)
        return clean_items
    if isinstance(value, dict):
        clean_map: dict[str, Any] = {}
        for child_key, child_value in value.items():
            if not isinstance(child_key, str):
                return _UNSUPPORTED
            clean = _sanitize_json_value(
                child_value, provenance=provenance, key=child_key
            )
            if clean is _UNSUPPORTED:
                return _UNSUPPORTED
            clean_map[child_key] = clean
        return clean_map
    return _UNSUPPORTED


def _sanitize_mapping(value: Optional[dict[str, Any]], *, provenance: bool) -> dict[str, Any]:
    clean = _sanitize_json_value(value or {}, provenance=provenance)
    return clean if isinstance(clean, dict) else {}


def sanitize_provenance(prov: dict[str, Any]) -> dict[str, Any]:
    """Create a detached, recursively sanitized provenance mapping."""
    return _sanitize_mapping(prov, provenance=True)


def sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Create a detached JSON-native metadata mapping."""
    return _sanitize_mapping(metadata, provenance=False)


class ToolStatus(str, Enum):
    """Execution status for a tool call."""
    SUCCESS = "success"
    ERROR = "error"
    BLOCKED = "blocked"
    DECLINED = "declined"
    EMPTY = "empty"
    JAVASCRIPT_REQUIRED = "javascript_required"
    BOT_CHALLENGE = "bot_challenge"
    RATE_LIMITED = "rate_limited"
    AUTH_REQUIRED = "auth_required"
    NOT_FOUND = "not_found"
    UNSUPPORTED_CONTENT = "unsupported_content"
    SSRF_BLOCKED = "ssrf_blocked"
    NETWORK_ERROR = "network_error"


class ToolKind(str, Enum):
    """Kind/category of tool result payload."""
    TEXT = "text"
    FILE = "file"
    WEB_PAGE = "web_page"
    EXECUTION = "execution"
    SEARCH = "search"
    OBSERVATION = "observation"
    SYSTEM = "system"


@runtime_checkable
class UrlProvenanceStoreProtocol(Protocol):
    """Protocol for runtime URL provenance validation."""
    def is_allowed(self, url: str) -> bool: ...
    def register_url(self, url: str, source: str) -> None: ...


@dataclass(frozen=True)
class ToolCallContext:
    """Session and provenance context passed to context-aware tools."""
    session_id: str
    workspace: Path
    turn_id: Optional[str] = None
    url_provenance: Optional[UrlProvenanceStoreProtocol] = None
    source: str = "agent_loop"


@dataclass(frozen=True)
class ToolResult:
    """Structured tool execution result.

    Invariants:
    - `public_error`: Sanitized error text presented to LLM/TUI.
    - `audit_error`: Redacted error text for persistence/tracing.
    - Raw exceptions are never stored in ToolResult.
    - `to_llm_text()`: Deterministic text representation for the model, never leaking paths, headers, raw exceptions or secrets.
    """
    status: ToolStatus
    kind: ToolKind
    payload: Any = ""
    public_error: Optional[str] = None
    audit_error: Optional[str] = None
    safe_provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Defensively sanitize all fields upon creation to prevent leak even on direct instantiation
        if self.public_error is not None:
            object.__setattr__(self, "public_error", redact_text(str(self.public_error)).text)
        if self.audit_error is not None:
            object.__setattr__(self, "audit_error", redact_text(str(self.audit_error)).text)
        if self.safe_provenance:
            object.__setattr__(self, "safe_provenance", sanitize_provenance(self.safe_provenance))
        if self.metadata:
            object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))

    def to_llm_text(self) -> str:
        """Render clean, status-adapted text for the LLM context window and TUI."""
        if self.status == ToolStatus.SUCCESS:
            if isinstance(self.payload, str):
                body = redact_text(self.payload).text
            else:
                clean_payload = _sanitize_json_value(self.payload)
                if clean_payload is _UNSUPPORTED:
                    body = "[unsupported payload type]"
                else:
                    body = json.dumps(
                        clean_payload,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                        allow_nan=False,
                    )

            if self.kind == ToolKind.WEB_PAGE and self.safe_provenance.get("url"):
                sanitized_url = sanitize_url_for_citation(str(self.safe_provenance["url"]))
                return f"{body}\n\n[Source: {sanitized_url}]"
            return body

        if self.status == ToolStatus.EMPTY:
            return "(inga resultat)"

        if self.status == ToolStatus.NOT_FOUND:
            msg = redact_text(self.public_error or "resource not found").text
            return f"[not found] {msg}"

        if self.status == ToolStatus.BLOCKED:
            msg = redact_text(self.public_error or "action blocked by safety policy").text
            return f"[blocked] {msg}"

        if self.status == ToolStatus.DECLINED:
            msg = redact_text(self.public_error or "declined by user").text
            return f"[declined] {msg}"

        if self.status == ToolStatus.JAVASCRIPT_REQUIRED:
            msg = redact_text(self.public_error or "page requires JavaScript").text
            return f"[javascript_required] {msg}"

        if self.status == ToolStatus.SSRF_BLOCKED:
            msg = redact_text(self.public_error or "destination address blocked").text
            return f"[ssrf_blocked] {msg}"

        err = redact_text(self.public_error or self.status.value).text
        return f"[{self.status.value}] {err}"


def create_success_result(
    kind: ToolKind,
    payload: Any,
    safe_provenance: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> ToolResult:
    """Factory helper for successful tool results."""
    clean_prov = sanitize_provenance(dict(safe_provenance)) if safe_provenance else {}
    clean_meta = sanitize_metadata(metadata or {})

    return ToolResult(
        status=ToolStatus.SUCCESS,
        kind=kind,
        payload=payload,
        safe_provenance=clean_prov,
        metadata=clean_meta,
    )


def create_error_result(
    status: ToolStatus,
    kind: ToolKind,
    raw_error: str | Exception,
    public_error: Optional[str] = None,
    safe_provenance: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> ToolResult:
    """Factory helper that redacts raw error strings for audit while providing a safe public message."""
    raw_str = str(raw_error)
    audit_redacted = redact_text(raw_str).text
    safe_public = public_error or "An error occurred during tool execution."
    safe_public_redacted = redact_text(safe_public).text
    clean_prov = sanitize_provenance(dict(safe_provenance)) if safe_provenance else {}
    clean_meta = sanitize_metadata(metadata or {})

    return ToolResult(
        status=status,
        kind=kind,
        payload="",
        public_error=safe_public_redacted,
        audit_error=audit_redacted,
        safe_provenance=clean_prov,
        metadata=clean_meta,
    )
