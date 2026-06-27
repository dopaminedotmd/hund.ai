"""CloudServer — HTTP server for fleet orchestration.

Manages connector registration, heartbeats, event aggregation,
and task deployment across the fleet.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

from ..connector.auth import generate_secret
from ..connector.intent import IntentRequest

_HEARTBEAT_TIMEOUT_S = 90
_HEARTBEAT_INTERVAL_S = 30
CLOUD_VERSION = "1.0.0"


class FleetState:
    """In-memory fleet state. Tracks connectors, heartbeats, events."""

    def __init__(self) -> None:
        self._connectors: dict[str, dict[str, Any]] = {}
        self._events: list[dict[str, Any]] = []
        self._max_events = 1000

    def register(self, connector_id: str, hostname: str, version: str, public_key: str = "") -> str:
        api_key = generate_secret()
        now = datetime.now(timezone.utc).isoformat()
        self._connectors[connector_id] = {
            "connector_id": connector_id,
            "hostname": hostname,
            "version": version,
            "public_key": public_key,
            "api_key": api_key,
            "registered_at": now,
            "last_seen": now,
            "status": "online",
            "load": 0,
        }
        return api_key

    def heartbeat(self, connector_id: str, status: str = "online", load: int = 0) -> bool:
        if connector_id not in self._connectors:
            return False
        now = datetime.now(timezone.utc).isoformat()
        self._connectors[connector_id]["last_seen"] = now
        self._connectors[connector_id]["status"] = status
        self._connectors[connector_id]["load"] = load
        return True

    def get_connector(self, connector_id: str) -> dict[str, Any] | None:
        return self._connectors.get(connector_id)

    def list_connectors(self) -> list[dict[str, Any]]:
        now = time.time()
        result = []
        for cid, info in self._connectors.items():
            connector = dict(info)
            connector.pop("api_key", None)
            # Calculate online/offline status based on heartbeat
            try:
                last = datetime.fromisoformat(connector["last_seen"]).timestamp()
                elapsed = now - last
                if elapsed > _HEARTBEAT_TIMEOUT_S:
                    connector["status"] = "offline"
            except (ValueError, TypeError):
                connector["status"] = "unknown"
            result.append(connector)
        return result

    def deregister(self, connector_id: str) -> bool:
        return self._connectors.pop(connector_id, None) is not None

    def add_event(self, connector_id: str, event: dict[str, Any]) -> None:
        event["_connector_id"] = connector_id
        event["_received_at"] = datetime.now(timezone.utc).isoformat()
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]

    def list_events(self, limit: int = 200) -> list[dict[str, Any]]:
        return self._events[-limit:]

    def get_connector_events(self, connector_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return [e for e in self._events if e.get("_connector_id") == connector_id][-limit:]


class _CloudHandler(BaseHTTPRequestHandler):
    def _json_response(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        content_len = int(self.headers.get("Content-Length", "0"))
        if content_len <= 0:
            return {}
        return json.loads(self.rfile.read(content_len).decode("utf-8"))

    def do_OPTIONS(self):
        self._json_response(200, {})

    def _get_state(self) -> FleetState:
        return self.server._fleet_state  # type: ignore

    def _handle_register(self):
        data = self._read_json_body()
        cid = data.get("connector_id", str(uuid.uuid4()))
        hostname = data.get("hostname", "unknown")
        version = data.get("version", "0.0.0")
        public_key = data.get("public_key", "")
        api_key = self._get_state().register(cid, hostname, version, public_key)
        self._json_response(201, {"connector_id": cid, "api_key": api_key, "status": "registered"})

    def _handle_fleet(self):
        connectors = self._get_state().list_connectors()
        self._json_response(200, {"fleet": connectors, "count": len(connectors)})

    def _handle_heartbeat(self):
        data = self._read_json_body()
        cid = data.get("connector_id", "")
        status = data.get("status", "online")
        load = data.get("load", 0)
        if not cid or not self._get_state().heartbeat(cid, status, load):
            self._json_response(404, {"status": "error", "reason": "unknown connector"})
            return
        self._json_response(200, {"status": "ok", "connector_id": cid})

    def _handle_deploy(self):
        data = self._read_json_body()
        cid = data.get("target_connector", "")
        connector = self._get_state().get_connector(cid)
        if not connector:
            self._json_response(404, {"status": "error", "reason": f"connector '{cid}' not found"})
            return
        if connector.get("status") == "offline":
            self._json_response(503, {"status": "error", "reason": f"connector '{cid}' is offline"})
            return
        # Build intent for deployment
        intent = IntentRequest(
            workspace_id=data.get("workspace_id", "cloud"),
            connector_id=cid,
            intent_type=data.get("intent_type", "tool_call"),
            tool_name=data.get("tool_name", ""),
            args_redacted=data.get("args", {}),
            org_id=data.get("org_id", ""),
        )
        # Sign with connector's api_key
        api_key = connector.get("api_key", "")
        from ..connector.auth import sign
        intent.signature = sign(intent, api_key)
        self._json_response(202, {"intent": intent.model_dump(), "connector_id": cid})

    def _handle_events(self):
        from urllib.parse import urlparse, parse_qs
        params = parse_qs(urlparse(self.path).query)
        cid = params.get("connector_id", [None])[0]
        limit_str = params.get("limit", ["200"])[0]
        try:
            limit = int(limit_str)
        except (ValueError, TypeError):
            limit = 200
        state = self._get_state()
        if cid:
            events = state.get_connector_events(cid, limit)
        else:
            events = state.list_events(limit)
        self._json_response(200, {"events": events, "count": len(events)})

    def _handle_connector_delete(self):
        parts = self.path.rstrip("/").split("/")
        if len(parts) < 4:
            self._json_response(400, {"status": "error", "reason": "missing connector_id"})
            return
        cid = parts[3]
        if self._get_state().deregister(cid):
            self._json_response(200, {"status": "deleted", "connector_id": cid})
        else:
            self._json_response(404, {"status": "error", "reason": "connector not found"})

    def _handle_forward_event(self):
        data = self._read_json_body()
        cid = data.get("connector_id", "unknown")
        event = data.get("event", {})
        self._get_state().add_event(cid, event)
        self._json_response(200, {"status": "ok"})

    def _handle_forge_evaluate(self):
        try:
            data = self._read_json_body()
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._json_response(400, {
                "error": "invalid_proposal",
                "message": str(exc),
                "retryable": False,
            })
            return

        expected_token = os.environ.get("HUND_FORGE_SERVICE_TOKEN", "")
        if expected_token:
            auth = self.headers.get("Authorization", "")
            if auth != f"Bearer {expected_token}":
                self._json_response(401, {
                    "error": "unauthorized",
                    "message": "Forge service token saknas eller är fel.",
                    "retryable": False,
                })
                return

        from ..forge.policy import ForgeProposal, evaluate_proposal_locally, idempotency_key
        from ..forge.registry import ForgeRegistry

        try:
            tenant_id = str(data.get("tenant_id") or "")
            proposal = ForgeProposal.from_dict(data.get("proposal") or {})
        except (TypeError, ValueError) as exc:
            self._json_response(400, {
                "error": "invalid_proposal",
                "message": str(exc),
                "retryable": False,
            })
            return
        if not tenant_id or not proposal.id:
            self._json_response(400, {
                "error": "invalid_proposal",
                "message": "tenant_id och proposal.id krävs.",
                "retryable": False,
            })
            return

        idem = self.headers.get("Idempotency-Key") or idempotency_key(proposal.id, tenant_id)
        registry = ForgeRegistry()
        cached = registry.get_cached_evaluation(idem)
        if cached:
            self._json_response(200, cached)
            return

        extra_text = json.dumps(
            {
                "persona_redacted": data.get("persona_redacted", ""),
                "context_redacted": data.get("context_redacted", {}),
            },
            ensure_ascii=False,
        )
        evaluation = evaluate_proposal_locally(
            proposal, tenant_id=tenant_id, idempotency=idem, extra_text=extra_text
        )
        response = evaluation.to_dict()
        if evaluation.verdict == "approved" or evaluation.state == "blocked_tcb":
            artifact = registry.stage_verified(
                tenant_id=tenant_id,
                proposal=proposal,
                evaluation=evaluation,
                payload=data,
                source="simulation" if data.get("simulation_source") else "real",
            )
            response["artifact"] = {
                "artifact_id": artifact.get("artifact_id"),
                "state": artifact.get("state"),
                "source": artifact.get("source"),
            }
        registry.cache_evaluation(
            idempotency_key=idem,
            proposal_id=proposal.id,
            tenant_id=tenant_id,
            request_redacted=data,
            response=response,
        )
        self._json_response(200, response)

    def _handle_health(self):
        self._json_response(200, {"version": CLOUD_VERSION, "status": "ok",
            "fleet_count": len(self._get_state().list_connectors())})

    def do_GET(self):
        if self.path == "/cloud/health":
            self._handle_health()
        elif self.path == "/cloud/fleet":
            self._handle_fleet()
        elif self.path.startswith("/cloud/events"):
            self._handle_events()
        elif self.path.startswith("/cloud/connectors/"):
            self._handle_connector_delete()
        else:
            self._json_response(404, {"status": "error", "reason": "not found"})

    def do_POST(self):
        if self.path == "/cloud/register":
            self._handle_register()
        elif self.path == "/cloud/heartbeat":
            self._handle_heartbeat()
        elif self.path == "/cloud/deploy":
            self._handle_deploy()
        elif self.path == "/cloud/events":
            self._handle_forward_event()
        elif self.path == "/forge/evaluate-proposal":
            self._handle_forge_evaluate()
        else:
            self._json_response(404, {"status": "error", "reason": "not found"})

    def do_DELETE(self):
        if self.path.startswith("/cloud/connectors/"):
            self._handle_connector_delete()
        else:
            self._json_response(404, {"status": "error", "reason": "not found"})

    def log_message(self, *args):
        pass


class CloudServer(HTTPServer):
    def __init__(self, port: int = 8765, bind: str = "0.0.0.0"):
        super().__init__((bind, port), _CloudHandler)
        self.timeout = 1
        self._fleet_state = FleetState()


def start_cloud(port: int = 8765, bind: str = "0.0.0.0") -> CloudServer:
    """Start the cloud orchestration server."""
    return CloudServer(port=port, bind=bind)
