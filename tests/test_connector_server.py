"""Tests for connector HTTP server — auth, permission, event stream."""

import json
import time
from pathlib import Path

import pytest

from hund.connector.auth import generate_secret, save_secret, sign
from hund.connector.intent import IntentRequest


@pytest.fixture
def secret_path(tmp_path: Path) -> Path:
    sp = tmp_path / "connector" / "key.json"
    save_secret("test-secret-for-testing", sp)
    return sp


@pytest.fixture
def user_secret_path(tmp_path: Path) -> Path:
    sp = tmp_path / "connector" / "user_key.json"
    save_secret("test-user-secret-for-testing", sp)
    return sp


def _server_thread(port: int, secret_path: Path, workspace_root: Path):
    """Start connector server in a thread. For use with pytest fixtures."""
    from hund.connector.server import start_connector

    server = start_connector(
        port=port,
        secret_path=secret_path,
        workspace_root=str(workspace_root),
    )
    while not getattr(server, "_stop", False):
        server.handle_request()
    server.server_close()


@pytest.fixture
def server_url(tmp_path: Path, secret_path: Path, user_secret_path: Path):
    """Start server on random port, return URL."""
    import socket
    import threading

    # Find free port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    ws = tmp_path / "workspace"
    ws.mkdir()

    from hund.connector.server import start_connector

    server = start_connector(
        port=port,
        secret_path=secret_path,
        workspace_root=str(ws),
        user_secret_path=user_secret_path,
    )

    def serve():
        while not getattr(server, "_stop", False):
            server.handle_request()
        server.server_close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    server._stop = True
    t.join(timeout=2)


def _intent_body(intent_type="health_check", **overrides) -> dict:
    """Build a valid signed IntentRequest dict."""
    intent = IntentRequest(
        workspace_id="ws-test",
        connector_id="ci-test",
        intent_type=intent_type,
        **overrides,
    )
    intent.signature = sign(intent, "test-secret-for-testing")
    return intent.model_dump()


def _sign_user_approval(approval) -> str:
    """Sign an ApprovalRequest with test user_secret."""
    import hashlib
    import hmac

    canonical = approval.canonical_signing_string().encode("utf-8")
    return hmac.new(
        b"test-user-secret-for-testing",
        canonical,
        hashlib.sha256,
    ).hexdigest()


def test_health_endpoint(server_url):
    import httpx

    resp = httpx.get(f"{server_url}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_intent_health(server_url):
    import httpx

    body = _intent_body(intent_type="health_check")
    resp = httpx.post(f"{server_url}/intent", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_intent_without_signature_returns_401(server_url):
    import httpx

    body = _intent_body(intent_type="tool_call", tool_name="read_file")
    body["signature"] = ""
    resp = httpx.post(f"{server_url}/intent", json=body)
    assert resp.status_code == 401
    data = resp.json()
    assert data["status"] == "denied"


def test_intent_with_wrong_signature_returns_401(server_url):
    import httpx

    body = _intent_body(intent_type="tool_call", tool_name="read_file")
    body["signature"] = "0" * 64
    resp = httpx.post(f"{server_url}/intent", json=body)
    assert resp.status_code == 401
    data = resp.json()
    assert "denied" in data["status"] or "denied" in data.get("reason", "")


def test_intent_replay_detected(server_url):
    """Send same intent twice — second should be rejected."""
    import httpx

    body = _intent_body(intent_type="health_check")
    resp1 = httpx.post(f"{server_url}/intent", json=body)
    assert resp1.status_code == 200

    resp2 = httpx.post(f"{server_url}/intent", json=body)
    assert resp2.status_code == 401
    data = resp2.json()
    assert "denied" in data.get("status", "")


def test_write_file_requires_approval(server_url):
    """WRITE tools should return 202 (pending approval) in Phase 6."""
    import httpx

    body = _intent_body(
        intent_type="tool_call",
        tool_name="write_file",
        args_redacted={"path": "test.txt", "content": "hello"},
    )
    resp = httpx.post(f"{server_url}/intent", json=body)
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "pending_approval"
    assert "approval_id" in data
    assert data["risk"] == "dangerous"


def test_terminal_requires_approval(server_url):
    """Terminal should return 202 (pending approval) in Phase 6."""
    import httpx

    body = _intent_body(
        intent_type="tool_call",
        tool_name="terminal",
        args_redacted={"command": "ls -la"},
    )
    resp = httpx.post(f"{server_url}/intent", json=body)
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "pending_approval"


def test_delete_file_requires_approval(server_url):
    """DANGEROUS tools should return 202 (pending approval) in Phase 6."""
    import httpx

    body = _intent_body(
        intent_type="tool_call",
        tool_name="delete_file",
        args_redacted={"path": "test.txt"},
    )
    resp = httpx.post(f"{server_url}/intent", json=body)
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "pending_approval"


def test_unknown_tool_returns_400(server_url):
    import httpx

    body = _intent_body(
        intent_type="tool_call",
        tool_name="nonexistent_tool_xyz",
        args_redacted={},
    )
    resp = httpx.post(f"{server_url}/intent", json=body)
    assert resp.status_code == 400


def test_event_stream_endpoint(server_url):
    import httpx

    body = _intent_body(
        intent_type="event_stream",
    )
    resp = httpx.post(f"{server_url}/intent", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert "events" in data
    assert isinstance(data["events"], list)


def test_events_get_endpoint(server_url):
    import httpx

    resp = httpx.get(f"{server_url}/events")
    assert resp.status_code == 200
    data = resp.json()
    assert "events" in data
