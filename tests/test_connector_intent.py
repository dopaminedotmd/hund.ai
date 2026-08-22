"""Tests for intent schema — serialization, validation, canonical signing."""

from hund.connector.intent import IntentRequest, IntentResponse


def test_intent_request_defaults():
    r = IntentRequest(workspace_id="ws1", connector_id="c1", intent_type="tool_call")
    assert r.schema_version == 1
    assert r.intent_type == "tool_call"
    assert r.workspace_id == "ws1"
    assert r.connector_id == "c1"
    assert r.risk_hint == "safe"
    assert len(r.intent_id) > 0
    assert len(r.nonce) > 0
    assert r.signature == ""


def test_intent_request_invalid_type():
    import pytest

    with pytest.raises(ValueError):
        IntentRequest(
            workspace_id="ws", connector_id="c", intent_type="invalid_type"
        )


def test_intent_request_invalid_risk():
    import pytest

    with pytest.raises(ValueError):
        IntentRequest(
            workspace_id="ws",
            connector_id="c",
            intent_type="tool_call",
            risk_hint="extreme",
        )


def test_canonical_signing_string_is_deterministic():
    r1 = IntentRequest(
        workspace_id="ws1",
        connector_id="c1",
        intent_type="tool_call",
        tool_name="read_file",
        nonce="abc123",
        intent_id="fixed-id",
        timestamp="2026-06-26T12:00:00+00:00",
    )
    r2 = IntentRequest(
        workspace_id="ws1",
        connector_id="c1",
        intent_type="tool_call",
        tool_name="read_file",
        nonce="abc123",
        intent_id="fixed-id",
        timestamp="2026-06-26T12:00:00+00:00",
    )
    assert r1.canonical_signing_string() == r2.canonical_signing_string()


def test_canonical_signing_string_excludes_signature():
    r = IntentRequest(
        workspace_id="ws1",
        connector_id="c1",
        intent_type="tool_call",
        signature="should_not_appear",
    )
    s = r.canonical_signing_string()
    assert "should_not_appear" not in s


def test_canonical_signing_schema():
    r = IntentRequest(
        workspace_id="ws-test",
        connector_id="c-test",
        intent_type="tool_call",
        tool_name="read_file",
        nonce="n1",
        timestamp="2021-01-01T00:00:00",
        expires_at="2021-01-01T01:00:00",
        org_id="org-99",
        run_id="run-42",
        session_id="sess-7",
        args_hash="h1",
    )
    s = r.canonical_signing_string()
    # Format: schema|intent_id|org|ws|connector|run|session|type|tool|args_hash|nonce|ts|expires|actor
    parts = s.split("|")
    assert parts[0] == "1"  # schema_version
    assert parts[2] == "org-99"  # org_id
    assert parts[3] == "ws-test"  # workspace_id
    assert parts[4] == "c-test"  # connector_id
    assert parts[5] == "run-42"  # run_id
    assert parts[6] == "sess-7"  # session_id
    assert parts[7] == "tool_call"  # intent_type
    assert parts[8] == "read_file"  # tool_name
    assert parts[9] == "h1"  # args_hash
    assert parts[10] == "n1"  # nonce


def test_intent_response_defaults():
    r = IntentResponse(intent_id="i1", status="ok")
    assert r.intent_id == "i1"
    assert r.status == "ok"
    assert r.risk == "none"
    assert r.reason == ""
    assert r.result_redacted is None
    assert r.trace_event_id is None


def test_intent_response_serializes():
    r = IntentResponse(
        intent_id="i1",
        status="blocked",
        risk="dangerous",
        reason="outside workspace",
    )
    d = r.model_dump()
    assert d["intent_id"] == "i1"
    assert d["status"] == "blocked"
    assert d["risk"] == "dangerous"
    assert d["reason"] == "outside workspace"
