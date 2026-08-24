"""Unit tests and security regression tests for Step 0 architectural contracts."""
from __future__ import annotations

import dataclasses
import math
from pathlib import Path
import pytest

from hund.tools.types import (
    ToolCallContext,
    ToolKind,
    ToolResult,
    ToolStatus,
    create_error_result,
    create_success_result,
    sanitize_url_for_citation,
)
from hund.tools.registry import Tool


def test_tool_status_enum_values():
    assert ToolStatus.SUCCESS.value == "success"
    assert ToolStatus.ERROR.value == "error"
    assert ToolStatus.BLOCKED.value == "blocked"
    assert ToolStatus.DECLINED.value == "declined"
    assert ToolStatus.EMPTY.value == "empty"
    assert ToolStatus.JAVASCRIPT_REQUIRED.value == "javascript_required"
    assert ToolStatus.BOT_CHALLENGE.value == "bot_challenge"
    assert ToolStatus.RATE_LIMITED.value == "rate_limited"
    assert ToolStatus.AUTH_REQUIRED.value == "auth_required"
    assert ToolStatus.NOT_FOUND.value == "not_found"
    assert ToolStatus.UNSUPPORTED_CONTENT.value == "unsupported_content"
    assert ToolStatus.SSRF_BLOCKED.value == "ssrf_blocked"
    assert ToolStatus.NETWORK_ERROR.value == "network_error"


def test_tool_kind_enum_values():
    assert ToolKind.TEXT.value == "text"
    assert ToolKind.FILE.value == "file"
    assert ToolKind.WEB_PAGE.value == "web_page"
    assert ToolKind.EXECUTION.value == "execution"
    assert ToolKind.SEARCH.value == "search"
    assert ToolKind.OBSERVATION.value == "observation"
    assert ToolKind.SYSTEM.value == "system"


def test_tool_call_context_immutability():
    ctx = ToolCallContext(
        session_id="sess_123",
        workspace=Path("/tmp/workspace"),
        turn_id="turn_456",
        url_provenance=None,
        source="agent_loop",
    )
    assert ctx.session_id == "sess_123"
    assert ctx.workspace == Path("/tmp/workspace")
    assert ctx.turn_id == "turn_456"
    assert ctx.source == "agent_loop"

    with pytest.raises(AttributeError):
        ctx.session_id = "sess_new"  # type: ignore


# 1. Secret in public_error reaches neither public_error attribute nor to_llm_text()
def test_regression_secret_in_public_error_never_reaches_llm():
    secret_token = "sk-1234567890abcdef1234567890"
    raw_error = f"Authentication failed with token={secret_token}"
    res = create_error_result(
        status=ToolStatus.ERROR,
        kind=ToolKind.TEXT,
        raw_error=raw_error,
        public_error=f"Failed to authenticate with token={secret_token}",
    )
    llm_output = res.to_llm_text()
    assert secret_token not in llm_output
    assert secret_token not in (res.public_error or "")
    assert "[REDACTED:secret]" in (res.public_error or "")

    # Direct construction test (cannot bypass redaction)
    direct_res = ToolResult(
        status=ToolStatus.ERROR,
        kind=ToolKind.TEXT,
        public_error=f"Secret leak api_key={secret_token}",
    )
    assert secret_token not in direct_res.to_llm_text()
    assert secret_token not in (direct_res.public_error or "")


# 2. Secret in safe_provenance URL never reaches to_llm_text()
def test_regression_secret_in_safe_provenance_url_never_reaches_llm():
    secret_key = "sk-1234567890abcdef1234567890"
    dirty_url = f"https://x.test/page?api_key={secret_key}&section=intro"
    
    res = create_success_result(
        kind=ToolKind.WEB_PAGE,
        payload="Page content summary",
        safe_provenance={"url": dirty_url, "title": "Secret Page"},
    )
    llm_output = res.to_llm_text()
    assert secret_key not in llm_output
    assert secret_key not in res.safe_provenance["url"]
    assert "https://x.test/page?section=intro" in llm_output

    # Direct construction test with userinfo in URL
    userinfo_url = f"https://admin:{secret_key}@internal.corp/docs"
    direct_res = ToolResult(
        status=ToolStatus.SUCCESS,
        kind=ToolKind.WEB_PAGE,
        payload="Internal Docs",
        safe_provenance={"url": userinfo_url},
    )
    direct_llm = direct_res.to_llm_text()
    assert secret_key not in direct_llm
    assert "admin:" not in direct_llm


# 3. Raw exception is not stored in dataclasses.asdict(result)
def test_regression_raw_exception_not_in_asdict():
    raw_exc = RuntimeError("Socket error on internal port 8080 at /Users/william/hund/secret.py")
    res = create_error_result(
        status=ToolStatus.NETWORK_ERROR,
        kind=ToolKind.WEB_PAGE,
        raw_error=raw_exc,
        public_error="Network timeout",
    )
    dump = dataclasses.asdict(res)
    assert "internal_error" not in dump
    assert "raw_error" not in dump
    # Audit error is sanitized
    assert "/Users/william" not in dump["audit_error"]
    assert "[REDACTED:path]" in dump["audit_error"]


# 4. Windows- and POSIX-paths are redacted in audit_error
def test_regression_paths_redacted_in_audit_error():
    win_path = r"C:\Users\William\AppData\Local\Secret\key.pem"
    posix_path = "/home/william/projects/secret/id_rsa"
    raw_err = f"Failed accessing {win_path} and {posix_path}"
    
    res = create_error_result(
        status=ToolStatus.ERROR,
        kind=ToolKind.FILE,
        raw_error=raw_err,
        public_error="File access failed",
    )
    audit = res.audit_error or ""
    assert r"C:\Users\William" not in audit
    assert "/home/william" not in audit
    assert "[REDACTED:path]" in audit


# 5. Dict/list-payload is rendered as deterministic JSON with sort_keys
def test_regression_dict_list_payload_deterministic_json():
    payload = {"z_key": 1, "a_key": 2, "m_key": [3, 2, 1]}
    res = create_success_result(
        kind=ToolKind.OBSERVATION,
        payload=payload,
    )
    llm_text = res.to_llm_text()
    expected_order = '{\n  "a_key": 2,\n  "m_key": [\n    3,\n    2,\n    1\n  ],\n  "z_key": 1\n}'
    assert llm_text == expected_order


# 6. Mutation of original metadata/provenance dict after factory call does not affect ToolResult
def test_regression_provenance_metadata_defensive_copies():
    original_prov = {"url": "https://example.com/docs", "tags": ["python"]}
    original_meta = {"latency_ms": 120}

    res = create_success_result(
        kind=ToolKind.WEB_PAGE,
        payload="Docs",
        safe_provenance=original_prov,
        metadata=original_meta,
    )

    # Mutate caller dicts
    original_prov["url"] = "https://malicious.com"
    original_prov["tags"].append("hacked")
    original_meta["latency_ms"] = 999999

    assert res.safe_provenance["url"] == "https://example.com/docs"
    assert res.metadata["latency_ms"] == 120


# 7. Non-serializable payload is handled deterministically without raw exception leak
def test_regression_unserializable_payload_handled_safely():
    class UnserializableObject:
        def __str__(self):
            return "UnserializableObject<Custom>"

    res = create_success_result(
        kind=ToolKind.EXECUTION,
        payload={"obj": UnserializableObject()},
    )
    llm_text = res.to_llm_text()
    assert llm_text == "[unsupported payload type]"


def test_nested_provenance_and_metadata_are_detached_and_sanitized():
    secret = "sk-1234567890abcdef1234567890"
    provenance = {"links": [{"url": f"https://safe.test/?api_key={secret}"}]}
    metadata = {"timing": {"samples": [1, 2]}}
    result = create_success_result(
        ToolKind.WEB_PAGE,
        "ok",
        safe_provenance=provenance,
        metadata=metadata,
    )

    provenance["links"][0]["url"] = f"https://evil.test/?token={secret}"
    metadata["timing"]["samples"].append(3)

    nested_url = result.safe_provenance["links"][0]["url"]
    assert secret not in nested_url
    assert result.metadata["timing"]["samples"] == [1, 2]


@pytest.mark.parametrize("scheme", ["javascript", "file", "data"])
def test_non_http_citation_schemes_are_suppressed(scheme: str):
    assert sanitize_url_for_citation(f"{scheme}:payload") == ""


@pytest.mark.parametrize("number", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_are_not_rendered_as_nonstandard_json(number: float):
    result = create_success_result(ToolKind.OBSERVATION, {"value": number})
    assert result.to_llm_text() == "[unsupported payload type]"


def test_default_object_repr_never_reaches_llm():
    result = create_success_result(ToolKind.EXECUTION, {"value": object()})
    text = result.to_llm_text()
    assert text == "[unsupported payload type]"
    assert " object at 0x" not in text


def test_status_adapted_text_and_error_representations():
    # Empty
    res_empty = ToolResult(
        status=ToolStatus.EMPTY,
        kind=ToolKind.SEARCH,
    )
    assert res_empty.to_llm_text() == "(inga resultat)"

    # Blocked
    res_blocked = ToolResult(
        status=ToolStatus.BLOCKED,
        kind=ToolKind.SYSTEM,
        public_error="Command blocked",
    )
    assert res_blocked.to_llm_text() == "[blocked] Command blocked"

    # Declined
    res_declined = ToolResult(
        status=ToolStatus.DECLINED,
        kind=ToolKind.FILE,
        public_error="Declined by user",
    )
    assert res_declined.to_llm_text() == "[declined] Declined by user"

    # Javascript required
    res_js = ToolResult(
        status=ToolStatus.JAVASCRIPT_REQUIRED,
        kind=ToolKind.WEB_PAGE,
        public_error="Page requires JavaScript",
    )
    assert res_js.to_llm_text() == "[javascript_required] Page requires JavaScript"

    # SSRF blocked
    res_ssrf = ToolResult(
        status=ToolStatus.SSRF_BLOCKED,
        kind=ToolKind.WEB_PAGE,
        public_error="Target address blocked",
    )
    assert res_ssrf.to_llm_text() == "[ssrf_blocked] Target address blocked"

    # Not found
    res_nf = ToolResult(
        status=ToolStatus.NOT_FOUND,
        kind=ToolKind.FILE,
        public_error="File not found",
    )
    assert res_nf.to_llm_text() == "[not found] File not found"


def test_tool_model_context_mode():
    tool = Tool(
        name="test_tool",
        description="A test tool",
        parameters={},
        base_risk="safe",
        context_mode="required",
    )
    assert tool.context_mode == "required"

    default_tool = Tool(
        name="legacy_tool",
        description="Legacy tool",
        parameters={},
        base_risk="safe",
    )
    assert default_tool.context_mode == "legacy"
    assert default_tool.handler is None
