"""Tests for Cloud Server — fleet management in memory."""

import json
from http.server import HTTPServer
from threading import Thread
from pathlib import Path

import pytest

from hund.cloud.server import CloudServer, FleetState, start_cloud


# ── FleetState ─────────────────────────────────────────────────────


def test_fleet_register():
    state = FleetState()
    api_key = state.register("c1", "host-1", "1.0.0")
    assert api_key is not None
    assert len(api_key) == 64


def test_fleet_heartbeat():
    state = FleetState()
    state.register("c1", "host-1", "1.0.0")
    assert state.heartbeat("c1", "online", 5) is True
    c = state.get_connector("c1")
    assert c["status"] == "online"
    assert c["load"] == 5


def test_heartbeat_unknown_returns_false():
    state = FleetState()
    assert state.heartbeat("nonexistent") is False


def test_list_connectors():
    state = FleetState()
    state.register("c1", "host-1", "1.0.0")
    state.register("c2", "host-2", "2.0.0")
    fleet = state.list_connectors()
    assert len(fleet) == 2


def test_list_connectors_hides_api_key():
    state = FleetState()
    state.register("c1", "host-1", "1.0.0")
    fleet = state.list_connectors()
    assert "api_key" not in fleet[0]


def test_deregister():
    state = FleetState()
    state.register("c1", "host-1", "1.0.0")
    assert state.deregister("c1") is True
    assert state.get_connector("c1") is None


def test_deregister_unknown():
    state = FleetState()
    assert state.deregister("nonexistent") is False


def test_add_and_list_events():
    state = FleetState()
    state.add_event("c1", {"event_type": "test", "data": "hello"})
    events = state.list_events()
    assert len(events) == 1
    assert events[0]["_connector_id"] == "c1"
    assert events[0]["_received_at"] is not None


def test_get_connector_events():
    state = FleetState()
    state.add_event("c1", {"event_type": "a"})
    state.add_event("c2", {"event_type": "b"})
    state.add_event("c1", {"event_type": "c"})
    c1_events = state.get_connector_events("c1")
    assert len(c1_events) == 2


def test_event_capacity():
    state = FleetState()
    state._max_events = 5
    for i in range(10):
        state.add_event("c1", {"event_type": f"e{i}"})
    assert len(state.list_events()) == 5


# ── CloudServer HTTP ────────────────────────────────────────────────


@pytest.fixture
def cloud_server():
    """Start a cloud server on a random port for testing."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = CloudServer(port=port, bind="127.0.0.1")

    def serve():
        while not getattr(server, "_stop", False):
            server.handle_request()
        server.server_close()

    t = Thread(target=serve, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    server._stop = True
    t.join(timeout=2)


def test_cloud_health(cloud_server):
    import httpx
    resp = httpx.get(f"{cloud_server}/cloud/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "fleet_count" in data


def test_cloud_register(cloud_server):
    import httpx
    resp = httpx.post(f"{cloud_server}/cloud/register", json={
        "connector_id": "c1", "hostname": "h1", "version": "1.0.0",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "registered"
    assert "api_key" in data


def test_cloud_fleet(cloud_server):
    import httpx
    httpx.post(f"{cloud_server}/cloud/register", json={
        "connector_id": "c1", "hostname": "h1", "version": "1.0.0",
    })
    resp = httpx.get(f"{cloud_server}/cloud/fleet")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1


def test_cloud_heartbeat(cloud_server):
    import httpx
    httpx.post(f"{cloud_server}/cloud/register", json={
        "connector_id": "c1", "hostname": "h1", "version": "1.0.0",
    })
    resp = httpx.post(f"{cloud_server}/cloud/heartbeat", json={
        "connector_id": "c1", "status": "online", "load": 3,
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_cloud_heartbeat_unknown(cloud_server):
    import httpx
    resp = httpx.post(f"{cloud_server}/cloud/heartbeat", json={
        "connector_id": "unknown", "status": "online",
    })
    assert resp.status_code == 404


def test_cloud_deploy(cloud_server):
    import httpx
    httpx.post(f"{cloud_server}/cloud/register", json={
        "connector_id": "c1", "hostname": "h1", "version": "1.0.0",
    })
    resp = httpx.post(f"{cloud_server}/cloud/deploy", json={
        "target_connector": "c1", "tool_name": "read_file", "args": {"path": "test.txt"},
    })
    assert resp.status_code == 202
    data = resp.json()
    assert "intent" in data


def test_cloud_deploy_unknown(cloud_server):
    import httpx
    resp = httpx.post(f"{cloud_server}/cloud/deploy", json={
        "target_connector": "nonexistent", "tool_name": "read_file",
    })
    assert resp.status_code == 404


def test_cloud_forward_event(cloud_server):
    import httpx
    resp = httpx.post(f"{cloud_server}/cloud/events", json={
        "connector_id": "c1", "event": {"event_type": "test"},
    })
    assert resp.status_code == 200


def test_cloud_delete_connector(cloud_server):
    import httpx
    httpx.post(f"{cloud_server}/cloud/register", json={
        "connector_id": "c1", "hostname": "h1", "version": "1.0.0",
    })
    resp = httpx.delete(f"{cloud_server}/cloud/connectors/c1")
    assert resp.status_code == 200
    # Verify it's gone
    fleet = httpx.get(f"{cloud_server}/cloud/fleet").json()
    assert fleet["count"] == 0


def test_cloud_cors_headers(cloud_server):
    import httpx
    resp = httpx.options(f"{cloud_server}/cloud/health")
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "*"


def test_cloud_register_auto_id(cloud_server):
    import httpx
    resp = httpx.post(f"{cloud_server}/cloud/register", json={
        "hostname": "auto-id", "version": "1.0.0",
    })
    data = resp.json()
    assert data["connector_id"] is not None
