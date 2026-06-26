"""Connector HTTP server — localhost endpoints for cloud-core communication.

Endpoints:
  POST /intent  — receive signed intent, validate, execute or deny
  GET  /events  — read-only trace event stream
  GET  /health  — server health + version
"""

from __future__ import annotations

import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

from .. import __version__
from ..agent.safety import PermissionEngine, RiskLevel
from ..trace.events import record_event
from .auth import verify, ReplayCache, load_secret
from .event_stream import query_events
from .intent import IntentRequest, IntentResponse

_SECRET_PATH = None  # Set by start_connector or injected for testing
_PERMISSION_ENGINE = None
_REPLAY_CACHE = ReplayCache()


def _get_secret() -> str | None:
    global _SECRET_PATH
    if _SECRET_PATH is None:
        return None
    return load_secret(_SECRET_PATH)


def _get_engine(workspace_root: str | None = None) -> PermissionEngine:
    global _PERMISSION_ENGINE
    if _PERMISSION_ENGINE is None:
        import os
        from pathlib import Path as P

        root = workspace_root or os.getcwd()
        _PERMISSION_ENGINE = PermissionEngine(
            workspace_root=P(root), mode="connector_remote"
        )
    return _PERMISSION_ENGINE


def _parse_json(body: bytes) -> dict[str, Any] | None:
    try:
        return json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _ev(name: str, integration: str, msg: str) -> None:
    """Best-effort trace event for connector operations."""
    try:
        record_event(
            workspace_id="connector",
            session_id="connector",
            run_id="connector",
            actor="connector",
            event_type=name,
            policy_version="1.0.0",
            payload_unredacted={integration: msg},
        )
    except Exception:
        pass


_DENIED_TOOLS = {"write_file", "delete_file", "execute_code", "delegate_task", "cronjob", "terminal"}


class ConnectorSink:
    def __init__(self) -> None:
        self.chunks: list[str] = []
        self.errors: list[str] = []
        self.tool_logs: list[str] = []

    def thinking(self, msg: str | None = None) -> None:
        pass

    def clear_thinking(self) -> None:
        pass

    def chunk(self, text: str) -> None:
        self.chunks.append(text)

    def end_assistant(self) -> None:
        pass

    def error(self, markup: str) -> None:
        self.errors.append(markup)

    def blocked(self, name: str, reason: str) -> None:
        self.tool_logs.append(f"Blocked tool {name}: {reason}")

    def declined(self, name: str, reason: str) -> None:
        self.tool_logs.append(f"Declined tool {name}: {reason}")

    def confirm(self, prompt: str) -> bool:
        # Non-interactive connector server: decline all confirmations in read-only phase
        return False

    def tool_start(self, name: str, args: dict) -> None:
        self.tool_logs.append(f"Starting tool {name}")

    def tool_result(self, name: str, result: str) -> None:
        self.tool_logs.append(f"Tool {name} result: {result}")


def _run_agent_turn(user_msg: str, session_id: str | None = None) -> dict[str, Any]:
    from ..agent import loop as agent_loop
    from ..agent import sessions as S
    from ..providers.base import Message
    from pathlib import Path
    import uuid

    if not session_id:
        active = S.get_active()
        if active:
            session_id = active["id"]
        else:
            session_id = S.create(title="Dashboard Chat")
    else:
        session_info = S.info(session_id)
        if not session_info:
            session_id = S.create(title="Dashboard Chat")

    messages: list[Message] = []
    cfg = agent_loop.HundConfig.load()
    workspace = (cfg.workspace_root or Path.cwd()).resolve()
    from ..tools.default_tools import register_defaults
    register_defaults(workspace)

    from ..persona import load_persona
    from ..doctor import profile_environment
    profile = profile_environment(workspace=workspace)
    persona = load_persona()

    try:
        from ..domains import detector as ddet
        from ..knowledge import store as kstore
        detection = ddet.detect(workspace)
        domain_hint = ddet.get_primary() or detection.primary
        knowledge = kstore.top_k(domain_hint, k=5) or kstore.top_k("general", k=5)
    except Exception:
        knowledge = []
    policy_rules = agent_loop._safe_policy_rules()
    skills = agent_loop._safe_skills()
    from .. import memory as _memory
    _memory.ensure_seed()
    memory_lines = _memory.inject()

    system_prompt = agent_loop.assemble_system_prompt(
        persona, profile, knowledge=knowledge, policy_rules=policy_rules,
        skills=skills, user_text=user_msg, memory_lines=memory_lines,
    )

    messages.append(Message(role="system", content=system_prompt))

    for role, content in S.history(session_id):
        messages.append(Message(role=role, content=content))

    messages.append(Message(role="user", content=user_msg))
    run_id = uuid.uuid4().hex

    agent_loop._session_save(session_id, "user", user_msg, run_id=run_id)

    key = agent_loop.load_api_key(cfg.provider.api_key_env)
    if not key:
        return {"status": "error", "reason": "HUND_API_KEY not configured"}

    client = agent_loop.OpenAICompatibleClient(cfg.provider.base_url, key, cfg.provider.model)
    engine = agent_loop.PermissionEngine(workspace_root=workspace, mode="connector_remote")
    schemas = agent_loop.registry.as_provider_schemas()

    tokens_before_compress = agent_loop.estimate_tokens(messages)
    comp = agent_loop.maybe_compress(messages, client=client)
    if comp.compressed:
        messages[:] = comp.messages
        agent_loop._trace_event(
            engine, session_id, run_id, "context_compressed",
            {
                "dropped_turns": comp.dropped_turns,
                "tokens_before": tokens_before_compress,
                "tokens_after": comp.tokens,
                "method": comp.method
            }
        )

    sink = ConnectorSink()
    from rich.console import Console
    mock_console = Console(width=80)

    agent_loop._agent_turn(
        mock_console,
        client,
        messages,
        schemas,
        engine,
        cfg,
        session_id,
        sink=sink,
        run_id=run_id
    )

    response_text = "".join(sink.chunks)
    if not response_text and sink.errors:
        response_text = f"Error: {' '.join(sink.errors)}"

    return {
        "status": "ok",
        "session_id": session_id,
        "run_id": run_id,
        "response": response_text,
        "tool_logs": sink.tool_logs
    }


class _Handler(BaseHTTPRequestHandler):
    """HTTP request handler for connector endpoints."""

    def _json_response(
        self, status: int, data: dict[str, Any]
    ) -> None:
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_intent(self) -> None:
        """POST /intent — receive signed intent, validate, execute or deny."""
        content_len = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_len)
        data = _parse_json(body)
        if data is None:
            self._json_response(400, {"status": "error", "reason": "invalid JSON"})
            return

        # Parse into IntentRequest
        try:
            intent = IntentRequest(**data)
        except Exception as exc:
            self._json_response(
                400,
                {"status": "error", "reason": f"invalid intent: {exc}"},
            )
            return

        # Get secret
        secret = _get_secret()
        if secret is None:
            self._json_response(
                503, {"status": "error", "reason": "connector not configured"}
            )
            return

        # Verify auth
        vr = verify(
            intent,
            secret,
            replay_cache=_REPLAY_CACHE,
        )
        if not vr.valid:
            _ev("tool_call_blocked", "intent_auth", vr.reason)
            self._json_response(
                401,
                {
                    "intent_id": intent.intent_id,
                    "status": "denied",
                    "reason": vr.reason,
                },
            )
            return

        # Route by intent_type
        if intent.intent_type == "health_check":
            self._json_response(200, {"status": "ok", "version": __version__})
            return

        if intent.intent_type == "event_stream":
            events = query_events(
                run_id=intent.run_id or None,
                session_id=intent.session_id or None,
                limit=200,
            )
            self._json_response(
                200,
                {
                    "intent_id": intent.intent_id,
                    "status": "ok",
                    "events": events,
                },
            )
            return

        if intent.intent_type == "tool_call":
            if not intent.tool_name:
                self._json_response(
                    400,
                    {"intent_id": intent.intent_id, "status": "error", "reason": "no tool_name"},
                )
                return

            # Phase 4: block write/confirm/dangerous tools
            if intent.tool_name in _DENIED_TOOLS:
                _ev("tool_call_blocked", "tool", f"denied {intent.tool_name} in Phase 4")
                self._json_response(
                    403,
                    {
                        "intent_id": intent.intent_id,
                        "status": "blocked",
                        "risk": "dangerous",
                        "reason": f"tool '{intent.tool_name}' requires approval gate (Phase 6)",
                    },
                )
                return

            # Check tool exists before PermissionEngine
            from ..tools.registry import get as get_tool

            tool_def = get_tool(intent.tool_name)
            if tool_def is None:
                self._json_response(
                    400,
                    {
                        "intent_id": intent.intent_id,
                        "status": "error",
                        "reason": f"unknown tool: {intent.tool_name}",
                    },
                )
                return

            # Classify via PermissionEngine
            engine = _get_engine()
            decision = engine.classify(intent.tool_name, intent.args_redacted)

            if decision.risk is RiskLevel.BLOCKED:
                _ev("tool_call_blocked", "permission", decision.reason)
                self._json_response(
                    403,
                    {
                        "intent_id": intent.intent_id,
                        "status": "blocked",
                        "risk": "blocked",
                        "reason": decision.reason,
                    },
                )
                return

            if decision.risk is not RiskLevel.SAFE:
                _ev("tool_call_blocked", "risk", f"risk {decision.risk.value} in Phase 4")
                self._json_response(
                    403,
                    {
                        "intent_id": intent.intent_id,
                        "status": "denied",
                        "risk": decision.risk.value,
                        "reason": f"risk {decision.risk.value} requires approval gate (Phase 6)",
                    },
                )
                return

            # SAFE — execute via tool registry
            from ..tools.registry import call

            try:
                result = call(intent.tool_name, intent.args_redacted)
            except Exception as exc:
                self._json_response(
                    500,
                    {
                        "intent_id": intent.intent_id,
                        "status": "error",
                        "reason": f"exec error: {exc}",
                    },
                )
                return

            resp = IntentResponse(
                intent_id=intent.intent_id,
                status="ok",
                risk="safe",
                result_redacted=result[:500] if result else "",
            )
            self._json_response(200, resp.model_dump())
            return

        self._json_response(
            400,
            {
                "intent_id": intent.intent_id,
                "status": "error",
                "reason": f"unknown intent_type: {intent.intent_type}",
            },
        )

    def _handle_events(self) -> None:
        """GET /events — read-only event stream."""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        run_id = params.get("run_id", [None])[0]
        session_id = params.get("session_id", [None])[0]
        event_type = params.get("event_type", [None])[0]
        since = params.get("since", [None])[0]

        events = query_events(
            run_id=run_id,
            session_id=session_id,
            event_type=event_type,
            since=since,
            limit=200,
        )
        self._json_response(200, {"events": events})

    def _handle_health(self) -> None:
        """GET /health — server health and version."""
        secret = _get_secret()
        self._json_response(
            200,
            {
                "version": __version__,
                "status": "ok",
                "configured": secret is not None,
            },
        )

    def _handle_traces(self) -> None:
        """GET /traces — read-only access to trace events database (with limit/offset/filters)."""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        try:
            limit = int(params.get("limit", [100])[0])
        except Exception:
            limit = 100
        try:
            offset = int(params.get("offset", [0])[0])
        except Exception:
            offset = 0

        filters = []
        args = []
        for key in ["run_id", "session_id", "event_type", "actor"]:
            if val := params.get(key, [None])[0]:
                filters.append(f"{key} = ?")
                args.append(val)

        query = "SELECT * FROM trace_events"
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])

        from ..store.sqlite import connect
        try:
            conn = connect()
            cursor = conn.cursor()
            rows = cursor.execute(query, args).fetchall()
            columns = [col[0] for col in cursor.description]
            conn.close()

            traces = []
            for row in rows:
                trace = dict(zip(columns, row))
                if "payload_redacted" in trace and trace["payload_redacted"]:
                    try:
                        trace["payload_redacted"] = json.loads(trace["payload_redacted"])
                    except Exception:
                        pass
                if "redaction" in trace and trace["redaction"]:
                    try:
                        trace["redaction"] = json.loads(trace["redaction"])
                    except Exception:
                        pass
                traces.append(trace)

            self._json_response(200, {"traces": traces})
        except Exception as exc:
            self._json_response(500, {"status": "error", "reason": f"Database error: {exc}"})

    def _handle_sessions(self) -> None:
        """GET /sessions — list sessions from the sessions database."""
        from ..agent import sessions as agent_sessions
        try:
            conn = agent_sessions._connect()
            cursor = conn.cursor()
            rows = cursor.execute("SELECT id, created_at, title, active, message_count FROM sessions ORDER BY created_at DESC").fetchall()
            conn.close()

            sessions = [
                {
                    "id": r[0],
                    "created_at": r[1],
                    "title": r[2],
                    "active": bool(r[3]),
                    "message_count": r[4],
                }
                for r in rows
            ]
            self._json_response(200, {"sessions": sessions})
        except Exception as exc:
            self._json_response(500, {"status": "error", "reason": f"Sessions DB error: {exc}"})

    def _handle_runs(self) -> None:
        """GET /runs — list unique runs with status and duration computed from trace events."""
        from ..store.sqlite import connect
        try:
            conn = connect()
            cursor = conn.cursor()
            rows = cursor.execute("""
                SELECT 
                    run_id,
                    MIN(created_at) as start,
                    MAX(created_at) as last_event,
                    SUM(CASE WHEN event_type = 'run_completed' THEN 1 ELSE 0 END) as is_completed,
                    MAX(CASE WHEN event_type = 'run_completed' THEN payload_redacted ELSE NULL END) as completed_payload
                FROM trace_events
                GROUP BY run_id
                ORDER BY start DESC
            """).fetchall()
            conn.close()

            runs = []
            for run_id, start, last_event, is_completed, completed_payload in rows:
                status = "running"
                if is_completed:
                    status = "completed"
                    if completed_payload:
                        try:
                            payload = json.loads(completed_payload)
                            if "error" in payload or payload.get("finish_reason") == "error":
                                status = "failed"
                        except Exception:
                            pass

                try:
                    from datetime import datetime
                    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    last_dt = datetime.fromisoformat(last_event.replace("Z", "+00:00"))
                    dur = (last_dt - start_dt).total_seconds()
                    duration = f"{dur:.1f}s"
                except Exception:
                    duration = "0.0s"

                runs.append({
                    "id": run_id,
                    "status": status,
                    "start": start,
                    "duration": duration
                })

            self._json_response(200, {"runs": runs})
        except Exception as exc:
            self._json_response(500, {"status": "error", "reason": f"Database error: {exc}"})

    def _handle_chat(self) -> None:
        """POST /chat — forward message to local agent loop."""
        content_len = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_len)
        data = _parse_json(body)
        if data is None or "message" not in data:
            self._json_response(400, {"status": "error", "reason": "invalid request or missing message"})
            return

        user_msg = data["message"]
        session_id = data.get("session_id")

        try:
            result = _run_agent_turn(user_msg, session_id)
            self._json_response(200, result)
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            self._json_response(500, {"status": "error", "reason": f"Agent error: {exc}\n{tb}"})

    def do_POST(self) -> None:
        if self.path == "/intent":
            self._handle_intent()
        elif self.path.startswith("/chat"):
            self._handle_chat()
        else:
            self._json_response(404, {"status": "error", "reason": "not found"})

    def do_GET(self) -> None:
        if self.path == "/health" or self.path == "/health/":
            self._handle_health()
            return
        if self.path.startswith("/events"):
            self._handle_events()
            return
        if self.path.startswith("/traces"):
            self._handle_traces()
            return
        if self.path.startswith("/sessions"):
            self._handle_sessions()
            return
        if self.path.startswith("/runs"):
            self._handle_runs()
            return
        self._json_response(404, {"status": "error", "reason": "not found"})

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default HTTP server logging."""
        pass


def start_connector(
    port: int = 7432,
    secret_path: Path | None = None,
    workspace_root: str | None = None,
    bind: str = "127.0.0.1",
) -> HTTPServer:
    """Start connector HTTP server. Blocks until KeyboardInterrupt.

    Args:
        port: Localhost port (default 7432).
        secret_path: Path to HMAC secret file.
        workspace_root: Workspace root for PermissionEngine.
        bind: Bind address (default 127.0.0.1).

    Returns:
        HTTPServer instance. Call .serve_forever() or .handle_request().
    """
    global _SECRET_PATH, _PERMISSION_ENGINE

    if secret_path is not None:
        _SECRET_PATH = secret_path
    if workspace_root is not None:
        from pathlib import Path as P

        _PERMISSION_ENGINE = PermissionEngine(
            workspace_root=P(workspace_root), mode="connector_remote"
        )

    server = HTTPServer((bind, port), _Handler)
    server.timeout = 1  # Allows KeyboardInterrupt to be caught
    return server
