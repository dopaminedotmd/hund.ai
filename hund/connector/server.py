"""Connector HTTP server — localhost endpoints with approval gate, worktree, export, and local model support."""
import hashlib, json, time
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
from .approval import ApprovalRequest, ApprovalResolveRequest, verify_approval_signature
from . import approval_store as approval_store_mod
from ..worktree.manager import WorktreeManager
from ..export.engine import ExportEngine, Filter as ExportFilter
from ..export import store as export_store
from ..local.engine import LocalEngine
from ..saas.chat import saas_chat
from ..stats.base_stats import compute_all as compute_stats
from ..domains.confidence import list_confidence as list_domain_confidence
from .cloud_agent import CloudAgent, CloudConfig

_SECRET_PATH = None
_PERMISSION_ENGINE = None
_REPLAY_CACHE = ReplayCache()
_USER_SECRET_PATH = None
_WORKTREE_MANAGER: WorktreeManager | None = None
_LOCAL_ENGINE: LocalEngine | None = None
_CLOUD_AGENT: CloudAgent | None = None
_DENIED_TOOLS = {"write_file", "delete_file", "execute_code", "delegate_task", "cronjob", "terminal"}


def _get_secret() -> str | None:
    global _SECRET_PATH
    if _SECRET_PATH is None:
        return None
    return load_secret(_SECRET_PATH)


def _get_user_secret() -> str | None:
    global _USER_SECRET_PATH
    if _USER_SECRET_PATH is None:
        return None
    return load_secret(_USER_SECRET_PATH)


def _get_worktree_manager() -> WorktreeManager:
    global _WORKTREE_MANAGER
    if _WORKTREE_MANAGER is None:
        import os
        _WORKTREE_MANAGER = WorktreeManager(repo_root=os.getcwd())
    return _WORKTREE_MANAGER


def _get_local_engine() -> LocalEngine:
    global _LOCAL_ENGINE
    if _LOCAL_ENGINE is None:
        _LOCAL_ENGINE = LocalEngine()
    return _LOCAL_ENGINE


def _get_cloud_agent() -> CloudAgent | None:
    global _CLOUD_AGENT
    if _CLOUD_AGENT is None:
        import os
        url = os.environ.get("HUND_CLOUD_URL", "")
        cid = os.environ.get("HUND_CLOUD_CONNECTOR_ID", "")
        api_key = os.environ.get("HUND_CLOUD_API_KEY", "")
        if url and api_key:
            _CLOUD_AGENT = CloudAgent(CloudConfig(url=url, connector_id=cid, api_key=api_key))
    return _CLOUD_AGENT


def _get_engine(workspace_root: str | None = None) -> PermissionEngine:
    global _PERMISSION_ENGINE
    if _PERMISSION_ENGINE is None:
        import os
        root = workspace_root or os.getcwd()
        _PERMISSION_ENGINE = PermissionEngine(workspace_root=Path(root), mode="connector_remote")
    return _PERMISSION_ENGINE


def _parse_json(body: bytes) -> dict[str, Any] | None:
    try:
        return json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _ev(name: str, integration: str, msg: str) -> None:
    try:
        record_event(workspace_id="connector", session_id="connector", run_id="connector",
                     actor="connector", event_type=name, policy_version="1.0.0",
                     payload_unredacted={integration: msg})
    except Exception:
        pass


class ConnectorSink:
    def __init__(self) -> None:
        self.chunks, self.errors, self.tool_logs = [], [], []

    def thinking(self, msg=None): pass
    def clear_thinking(self): pass
    def chunk(self, text): self.chunks.append(text)
    def end_assistant(self): pass
    def error(self, markup): self.errors.append(markup)
    def blocked(self, name, reason): self.tool_logs.append(f"Blocked tool {name}: {reason}")
    def declined(self, name, reason): self.tool_logs.append(f"Declined tool {name}: {reason}")
    def confirm(self, prompt): return False
    def tool_start(self, name, args): self.tool_logs.append(f"Starting tool {name}")
    def tool_result(self, name, result): self.tool_logs.append(f"Tool {name} result: {result}")


def _run_agent_turn(user_msg: str, session_id: str | None = None) -> dict[str, Any]:
    from ..agent import loop as agent_loop, sessions as S
    from ..providers.base import Message
    import uuid

    if not session_id:
        active = S.get_active()
        session_id = active["id"] if active else S.create(title="Dashboard Chat")
    else:
        if not S.info(session_id):
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
    system_prompt = agent_loop.assemble_system_prompt(persona, profile, knowledge=knowledge,
        policy_rules=policy_rules, skills=skills, user_text=user_msg, memory_lines=memory_lines)
    messages.append(Message(role="system", content=system_prompt))
    for role, content in S.history(session_id):
        messages.append(Message(role=role, content=content))
    messages.append(Message(role="user", content=user_msg))
    run_id = uuid.uuid4().hex
    agent_loop._session_save(session_id, "user", user_msg, run_id=run_id)
    key = agent_loop.load_api_key(cfg.provider.api_key_env)

    if key:
        client = agent_loop.OpenAICompatibleClient(cfg.provider.base_url, key, cfg.provider.model)
    else:
        from ..providers.local import LocalProvider
        local_engine = _get_local_engine()
        client = LocalProvider(engine=local_engine)

    engine = agent_loop.PermissionEngine(workspace_root=workspace, mode="connector_remote")
    schemas = agent_loop.registry.as_provider_schemas()
    tokens_before_compress = agent_loop.estimate_tokens(messages)
    comp = agent_loop.maybe_compress(messages, client=client)
    if comp.compressed:
        messages[:] = comp.messages
        agent_loop._trace_event(engine, session_id, run_id, "context_compressed",
            {"dropped_turns": comp.dropped_turns, "tokens_before": tokens_before_compress,
             "tokens_after": comp.tokens, "method": comp.method})
    sink = ConnectorSink()
    from rich.console import Console
    mock_console = Console(width=80)
    agent_loop._agent_turn(mock_console, client, messages, schemas, engine, cfg, session_id, sink=sink, run_id=run_id)
    response_text = "".join(sink.chunks) or f"Error: {' '.join(sink.errors)}"
    return {"status": "ok", "session_id": session_id, "run_id": run_id, "response": response_text, "tool_logs": sink.tool_logs}


def _handle_approval_resolve_inner(body: dict[str, Any]) -> dict[str, Any]:
    resolve_req = ApprovalResolveRequest(**body)
    if resolve_req.user_decision not in {"approved", "denied"}:
        return {"status": 400, "data": {"status": "error", "reason": "invalid decision"}}
    user_secret = _get_user_secret()
    if user_secret is None:
        return {"status": 503, "data": {"status": "error", "reason": "user_secret not configured"}}
    resolved = approval_store_mod.resolve_approval(approval_id=resolve_req.approval_id,
        user_decision=resolve_req.user_decision, user_signature=resolve_req.user_signature)
    if resolved is None:
        return {"status": 404, "data": {"status": "error", "reason": "approval not found or already resolved"}}
    record_event(workspace_id=resolved.workspace_id or "unknown", session_id=resolved.connector_id or "connector",
        run_id="connector", actor="user", event_type="approval_resolved", policy_version="1.0.0",
        risk=resolved.risk_level, tool_name=resolved.tool_name, approval_id=resolved.approval_id,
        payload_unredacted={"user_decision": resolved.user_decision, "approval_id": resolved.approval_id, "tool_name": resolved.tool_name})
    if resolve_req.user_decision == "denied":
        return {"status": 200, "data": {"status": "denied", "approval_id": resolved.approval_id}}
    if resolve_req.user_signature and not verify_approval_signature(resolved, user_secret):
        return {"status": 403, "data": {"status": "error", "reason": "signature mismatch", "approval_id": resolved.approval_id}}
    if resolved.is_expired(timeout_s=300):
        return {"status": 408, "data": {"status": "timeout", "reason": "approval timed out", "approval_id": resolved.approval_id}}
    payload = resolved.intent_payload
    tool_name = payload.get("tool_name", resolved.tool_name)
    args = payload.get("args_redacted", {})
    from ..tools.registry import call, get as get_tool
    if get_tool(tool_name) is None:
        return {"status": 200, "data": {"status": "ok", "approval_id": resolved.approval_id,
            "note": f"tool '{tool_name}' approved but not executable locally"}}
    try:
        result = call(tool_name, args)
        return {"status": 200, "data": {"status": "ok", "approval_id": resolved.approval_id, "result": str(result)[:500]}}
    except Exception as exc:
        return {"status": 500, "data": {"status": "error", "reason": f"exec error: {exc}"}}


class _Handler(BaseHTTPRequestHandler):
    def _json_response(self, status: int, data):
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_intent(self):
        content_len = int(self.headers.get("Content-Length", "0"))
        data = _parse_json(self.rfile.read(content_len))
        if data is None:
            return self._json_response(400, {"status": "error", "reason": "invalid JSON"})
        try:
            intent = IntentRequest(**data)
        except Exception as exc:
            return self._json_response(400, {"status": "error", "reason": f"invalid intent: {exc}"})
        secret = _get_secret()
        if secret is None:
            return self._json_response(503, {"status": "error", "reason": "connector not configured"})
        vr = verify(intent, secret, replay_cache=_REPLAY_CACHE)
        if not vr.valid:
            _ev("tool_call_blocked", "intent_auth", vr.reason)
            return self._json_response(401, {"intent_id": intent.intent_id, "status": "denied", "reason": vr.reason})
        if intent.intent_type == "health_check":
            return self._json_response(200, {"status": "ok", "version": __version__})
        if intent.intent_type == "event_stream":
            return self._json_response(200, {"intent_id": intent.intent_id, "status": "ok",
                "events": query_events(run_id=intent.run_id or None, session_id=intent.session_id or None, limit=200)})
        if intent.intent_type == "tool_call":
            if not intent.tool_name:
                return self._json_response(400, {"intent_id": intent.intent_id, "status": "error", "reason": "no tool_name"})
            if intent.tool_name in _DENIED_TOOLS:
                risk_str = "dangerous"
            else:
                from ..tools.registry import get as get_tool
                if get_tool(intent.tool_name) is None:
                    return self._json_response(400, {"intent_id": intent.intent_id, "status": "error", "reason": f"unknown tool: {intent.tool_name}"})
                engine = _get_engine()
                decision = engine.classify(intent.tool_name, intent.args_redacted)
                if decision.risk is RiskLevel.BLOCKED:
                    return self._json_response(403, {"intent_id": intent.intent_id, "status": "blocked", "risk": "blocked", "reason": decision.reason})
                if decision.risk is RiskLevel.SAFE:
                    from ..tools.registry import call
                    try:
                        result = call(intent.tool_name, intent.args_redacted)
                        return self._json_response(200, IntentResponse(intent_id=intent.intent_id, status="ok",
                            risk="safe", result_redacted=str(result)[:500] if result else "").model_dump())
                    except Exception as exc:
                        return self._json_response(500, {"intent_id": intent.intent_id, "status": "error", "reason": f"exec error: {exc}"})
                risk_str = decision.risk.value
            user_secret = _get_user_secret()
            if user_secret is None:
                return self._json_response(503, {"intent_id": intent.intent_id, "status": "error", "reason": "user_secret not configured for approval gate"})
            approval = approval_store_mod.create_approval(intent_id=intent.intent_id, tool_name=intent.tool_name,
                args_hash=intent.args_hash, risk_level=risk_str, workspace_id=intent.workspace_id,
                connector_id=intent.connector_id, intent_payload={"intent_type": intent.intent_type,
                "tool_name": intent.tool_name, "args_redacted": intent.args_redacted, "run_id": intent.run_id,
                "session_id": intent.session_id, "actor": intent.actor})
            record_event(workspace_id=intent.workspace_id, session_id=intent.session_id, run_id=intent.run_id or "unknown",
                actor="connector", event_type="approval_requested", policy_version="1.0.0", risk=risk_str,
                tool_name=intent.tool_name, approval_id=approval.approval_id,
                payload_unredacted={"tool_name": intent.tool_name, "risk_level": risk_str, "args_hash": intent.args_hash,
                "approval_id": approval.approval_id, "nonce": approval.nonce})
            return self._json_response(202, {"intent_id": intent.intent_id, "status": "pending_approval",
                "risk": risk_str, "approval_id": approval.approval_id, "nonce": approval.nonce,
                "reason": f"tool '{intent.tool_name}' requires user approval (risk={risk_str})"})
        self._json_response(400, {"intent_id": intent.intent_id, "status": "error", "reason": f"unknown intent_type: {intent.intent_type}"})

    def _handle_approvals_pending(self):
        self._json_response(200, {"approvals": approval_store_mod.get_pending_approvals()})

    def _handle_approval_resolve(self):
        data = _parse_json(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if data is None:
            return self._json_response(400, {"status": "error", "reason": "invalid JSON"})
        try:
            result = _handle_approval_resolve_inner(data)
        except Exception as exc:
            return self._json_response(500, {"status": "error", "reason": str(exc)})
        self._json_response(result["status"], result["data"])

    def _handle_approval_cancel(self):
        data = _parse_json(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if data is None:
            return self._json_response(400, {"status": "error", "reason": "invalid JSON"})
        approval_id = data.get("approval_id", "")
        if not approval_id:
            return self._json_response(400, {"status": "error", "reason": "missing approval_id"})
        cancelled = approval_store_mod.cancel_approval(approval_id)
        if cancelled is None:
            return self._json_response(404, {"status": "error", "reason": "approval not found or already resolved"})
        self._json_response(200, {"status": "cancelled", "approval_id": approval_id})

    def _handle_worktrees_list(self):
        try:
            self._json_response(200, {"worktrees": _get_worktree_manager().list_worktrees()})
        except Exception as exc:
            self._json_response(500, {"status": "error", "reason": str(exc)})

    def _handle_worktree_create(self):
        data = _parse_json(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if data is None:
            return self._json_response(400, {"status": "error", "reason": "invalid JSON"})
        branch, base = data.get("branch", ""), data.get("base", "main")
        if not branch:
            return self._json_response(400, {"status": "error", "reason": "missing branch"})
        try:
            path = _get_worktree_manager().create_worktree(branch, base=base)
            self._json_response(201, {"branch": branch, "path": str(path), "status": "created"})
        except Exception as exc:
            self._json_response(409, {"status": "error", "reason": str(exc)})

    def _handle_worktree_delete(self):
        data = _parse_json(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if data is None:
            return self._json_response(400, {"status": "error", "reason": "invalid JSON"})
        branch = data.get("branch", "")
        if not branch:
            return self._json_response(400, {"status": "error", "reason": "missing branch"})
        try:
            _get_worktree_manager().delete_worktree(branch)
            self._json_response(200, {"branch": branch, "status": "deleted"})
        except Exception as exc:
            self._json_response(404, {"status": "error", "reason": str(exc)})

    def _handle_worktree_branch_action(self):
        parts = self.path.rstrip("/").split("/")
        branch = parts[2] if len(parts) > 2 else ""
        action = parts[3] if len(parts) > 3 else ""
        if not branch or not action:
            return self._json_response(400, {"status": "error", "reason": "missing branch or action"})
        mgr = _get_worktree_manager()
        if self.command == "GET":
            if action == "diff":
                base = parse_qs(urlparse(self.path).query).get("base", ["main"])[0]
                try:
                    diff = mgr.get_diff(branch, base=base)
                    self._json_response(200, {"branch": branch, "base": base, "diff": diff, "diff_lines": len(diff.split("\n")) if diff else 0})
                except Exception as exc:
                    self._json_response(404, {"status": "error", "reason": str(exc)})
            elif action == "commits":
                try:
                    commits = mgr.get_commit_log(branch, max_count=20)
                    self._json_response(200, {"branch": branch, "commits": commits, "commit_count": len(commits)})
                except Exception as exc:
                    self._json_response(404, {"status": "error", "reason": str(exc)})
            else:
                self._json_response(404, {"status": "error", "reason": f"unknown action: {action}"})
        elif self.command == "POST":
            data = _parse_json(self.rfile.read(int(self.headers.get("Content-Length", "0")))) or {}
            if action == "propose":
                try:
                    proposal = mgr.propose(branch, title=data.get("title", ""), base=data.get("base", "main"))
                    record_event(workspace_id="worktree", session_id=branch, run_id=proposal["proposal_id"],
                        actor="worktree_agent", event_type="worktree_proposed", policy_version="1.0.0",
                        risk="worktree", tool_name="worktree_propose", payload_unredacted=proposal)
                    self._json_response(200, proposal)
                except Exception as exc:
                    self._json_response(500, {"status": "error", "reason": str(exc)})
            elif action == "merge":
                try:
                    result = mgr.merge_to_main(branch, base=data.get("base", "main"))
                    record_event(workspace_id="worktree", session_id=branch, run_id=result.get("merge_hash", ""),
                        actor="worktree_agent", event_type="worktree_merged", policy_version="1.0.0",
                        risk="worktree", tool_name="worktree_merge", payload_unredacted=result)
                    self._json_response(200, result)
                except Exception as exc:
                    self._json_response(500, {"status": "error", "reason": str(exc)})
            else:
                self._json_response(404, {"status": "error", "reason": f"unknown action: {action}"})

    def _handle_export_list(self):
        self._json_response(200, {"exports": export_store.list_exports(limit=50)})

    def _handle_export_preview(self):
        params = parse_qs(urlparse(self.path).query)
        filt = ExportFilter()
        if s := params.get("session_id", [None])[0]: filt = filt.with_session(s)
        if e := params.get("event_type", [None])[0]: filt = filt.with_event_type(e)
        if r := params.get("run_id", [None])[0]: filt = filt.with_run(r)
        try:
            filt = filt.with_limit(int(params.get("limit", ["50"])[0]))
        except (ValueError, TypeError): pass
        try:
            stats = ExportEngine().dry_run(ExportEngine().build_pairs(filt))
            stats["filter"] = filt.to_dict()
            self._json_response(200, stats)
        except Exception as exc:
            self._json_response(500, {"status": "error", "reason": str(exc)})

    def _handle_export_run(self):
        data = _parse_json(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if data is None:
            return self._json_response(400, {"status": "error", "reason": "invalid JSON"})
        fmt = data.get("format", "jsonl")
        if fmt not in ("jsonl", "sft"):
            return self._json_response(400, {"status": "error", "reason": "unsupported format"})
        filt = ExportFilter()
        if s := data.get("session_id"): filt = filt.with_session(s)
        if e := data.get("event_type"): filt = filt.with_event_type(e)
        if r := data.get("run_id"): filt = filt.with_run(r)
        try:
            filt = filt.with_limit(int(data.get("limit", 200)))
        except (ValueError, TypeError): pass
        try:
            engine = ExportEngine()
            pairs = engine.build_pairs(filt)
            out_path = Path(f"exports/hund_export_{int(time.time())}.{fmt}")
            (engine.export_to_jsonl if fmt == "jsonl" else engine.export_to_sft)(pairs, out_path)
            engine.save_manifest(pairs, out_path, filter_obj=filt, export_format=fmt)
            eid = export_store.log_export(export_format=fmt, pair_count=len(pairs), output_path=str(out_path.resolve()),
                filters_json=json.dumps(filt.to_dict(), ensure_ascii=False))
            record_event(workspace_id="connector", session_id="export", run_id=eid, actor="connector",
                event_type="export_completed", policy_version="1.0.0", risk="none", tool_name="export",
                payload_unredacted={"export_id": eid, "format": fmt, "pair_count": len(pairs), "output_path": str(out_path.resolve())})
            self._json_response(201, {"status": "ok", "export_id": eid, "format": fmt, "pair_count": len(pairs), "output_path": str(out_path.resolve())})
        except Exception as exc:
            self._json_response(500, {"status": "error", "reason": str(exc)})

    def _handle_saas_chat(self):
        """POST /api/saas/chat — SaaS chat endpoint (pure LLM, no tools)."""
        data = _parse_json(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if data is None or "message" not in data:
            return self._json_response(400, {"status": "error", "reason": "missing message"})
        try:
            result = saas_chat(
                message=data["message"],
                session_id=data.get("session_id"),
                customer_info=data.get("customer_info"),
            )
            self._json_response(200, result)
        except RuntimeError as exc:
            self._json_response(503, {"status": "error", "reason": str(exc)})
        except Exception as exc:
            self._json_response(500, {"status": "error", "reason": str(exc)})

    def _handle_saas_stats(self):
        """GET /api/saas/stats — all 5 base stats."""
        try:
            stats = compute_stats()
            self._json_response(200, {"stats": stats})
        except Exception as exc:
            self._json_response(500, {"status": "error", "reason": str(exc)})

    def _handle_saas_domains(self):
        """GET /api/saas/domains — domain confidence scores."""
        try:
            domains = list_domain_confidence()
            self._json_response(200, {"domains": domains})
        except Exception as exc:
            self._json_response(500, {"status": "error", "reason": str(exc)})

    def _handle_events(self):
        p = parse_qs(urlparse(self.path).query)
        self._json_response(200, {"events": query_events(run_id=p.get("run_id", [None])[0],
            session_id=p.get("session_id", [None])[0], event_type=p.get("event_type", [None])[0],
            since=p.get("since", [None])[0], limit=200)})

    def _handle_health(self):
        le = _get_local_engine()
        ca = _get_cloud_agent()
        local_info = {"running": le.is_running, "model": str(le.model_path or "")}
        cloud_info = {"connected": ca is not None and ca.is_connected, "url": ca.cloud_url if ca else ""}
        self._json_response(200, {"version": __version__, "status": "ok",
            "configured": _get_secret() is not None, "approval_gate": _get_user_secret() is not None,
            "local_engine": local_info, "cloud": cloud_info})

    def _handle_traces(self):
        p = parse_qs(urlparse(self.path).query)
        from ..store.sqlite import connect
        try:
            limit, offset = int(p.get("limit", [100])[0]), int(p.get("offset", [0])[0])
        except Exception:
            limit, offset = 100, 0
        filters, args = [], []
        for key in ["run_id", "session_id", "event_type", "actor"]:
            if v := p.get(key, [None])[0]:
                filters.append(f"{key}=?"); args.append(v)
        q = "SELECT * FROM trace_events" + (" WHERE " + " AND ".join(filters) if filters else "") + " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        try:
            conn = connect(); rows = conn.execute(q, args).fetchall()
            cols = [c[0] for c in conn.execute("PRAGMA table_info(trace_events)").fetchall()]; conn.close()
            traces = []
            for row in rows:
                t = dict(zip(cols, row))
                if t.get("payload_redacted"):
                    try: t["payload_redacted"] = json.loads(t["payload_redacted"])
                    except Exception: pass
                if t.get("redaction"):
                    try: t["redaction"] = json.loads(t["redaction"])
                    except Exception: pass
                traces.append(t)
            self._json_response(200, {"traces": traces})
        except Exception as exc:
            self._json_response(500, {"status": "error", "reason": f"Database error: {exc}"})

    def _handle_sessions(self):
        from ..agent import sessions as agent_sessions
        try:
            conn = agent_sessions._connect()
            rows = conn.execute("SELECT id, created_at, title, active, message_count FROM sessions ORDER BY created_at DESC").fetchall()
            conn.close()
            self._json_response(200, {"sessions": [{"id": r[0], "created_at": r[1], "title": r[2], "active": bool(r[3]), "message_count": r[4]} for r in rows]})
        except Exception as exc:
            self._json_response(500, {"status": "error", "reason": f"Sessions DB error: {exc}"})

    def _handle_runs(self):
        from ..store.sqlite import connect
        try:
            conn = connect()
            rows = conn.execute("""SELECT run_id, MIN(created_at), MAX(created_at),
                SUM(CASE WHEN event_type='run_completed' THEN 1 ELSE 0 END) FROM trace_events GROUP BY run_id ORDER BY MIN(created_at) DESC""").fetchall()
            conn.close()
            runs = [{"id": r[0], "status": "running" if not r[3] else "completed", "start": r[1], "duration": "0s"} for r in rows]
            self._json_response(200, {"runs": runs})
        except Exception as exc:
            self._json_response(500, {"status": "error", "reason": f"Database error: {exc}"})

    def _handle_chat(self):
        data = _parse_json(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if data is None or "message" not in data:
            return self._json_response(400, {"status": "error", "reason": "invalid request"})
        try:
            self._json_response(200, _run_agent_turn(data["message"], data.get("session_id")))
        except Exception as exc:
            import traceback
            self._json_response(500, {"status": "error", "reason": f"Agent error: {exc}\n{traceback.format_exc()}"})

    def do_POST(self):
        if self.path == "/intent": self._handle_intent()
        elif self.path == "/api/saas/chat": self._handle_saas_chat()
        elif self.path == "/approvals/resolve": self._handle_approval_resolve()
        elif self.path == "/approvals/cancel": self._handle_approval_cancel()
        elif self.path == "/exports/run": self._handle_export_run()
        elif self.path == "/worktrees/create": self._handle_worktree_create()
        elif self.path == "/worktrees/delete": self._handle_worktree_delete()
        elif self.path.startswith("/worktrees/"): self._handle_worktree_branch_action()
        elif self.path.startswith("/chat"): self._handle_chat()
        else: self._json_response(404, {"status": "error", "reason": "not found"})

    def do_GET(self):
        if self.path in ("/health", "/health/"): self._handle_health(); return
        if self.path == "/api/saas/stats": self._handle_saas_stats(); return
        if self.path == "/api/saas/domains": self._handle_saas_domains(); return
        if self.path.startswith("/events"): self._handle_events(); return
        if self.path.startswith("/traces"): self._handle_traces(); return
        if self.path.startswith("/sessions"): self._handle_sessions(); return
        if self.path.startswith("/runs"): self._handle_runs(); return
        if self.path == "/approvals/pending": self._handle_approvals_pending(); return
        if self.path == "/exports/list": self._handle_export_list(); return
        if self.path.startswith("/exports/preview"): self._handle_export_preview(); return
        if self.path == "/worktrees/list": self._handle_worktrees_list(); return
        if self.path.startswith("/worktrees/"): self._handle_worktree_branch_action(); return
        self._json_response(404, {"status": "error", "reason": "not found"})

    def log_message(self, *args): pass


def start_connector(port=7432, secret_path=None, workspace_root=None, bind="127.0.0.1", user_secret_path=None):
    global _SECRET_PATH, _PERMISSION_ENGINE, _USER_SECRET_PATH
    if secret_path is not None: _SECRET_PATH = secret_path
    if user_secret_path is not None: _USER_SECRET_PATH = user_secret_path
    if workspace_root is not None:
        _PERMISSION_ENGINE = PermissionEngine(workspace_root=Path(workspace_root), mode="connector_remote")
    server = HTTPServer((bind, port), _Handler)
    server.timeout = 1
    return server
