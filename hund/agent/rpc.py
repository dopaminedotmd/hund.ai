"""RPC-lager for tool-anrop fran subprocess. JSON-line via stdin/stdout."""
from __future__ import annotations
import json
import sys
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ToolRequest:
    id: int
    tool: str
    args: dict = field(default_factory=dict)

@dataclass
class ToolResponse:
    id: int
    result: str = ""
    error: str | None = None

# --- Child-side: importeras av det genererade scriptet ---

def call_tool(tool: str, args: dict | None = None) -> str:
    """Anropa ett tool fran child-processen. Blocking."""
    args = args or {}
    req = {"type": "request", "id": 1, "tool": tool, "args": args}
    # Skicka request via stdout (parent laser)
    sys.stdout.write(json.dumps(req, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    # Las response fran stdin (parent skriver)
    line = sys.stdin.readline()
    if not line:
        return "[error] ingen response fran parent"
    try:
        resp = json.loads(line)
    except json.JSONDecodeError:
        return f"[error] invalid JSON: {line[:100]}"
    if resp.get("error"):
        return f"[error] {resp['error']}"
    return resp.get("result", "")

# --- Parent-side: anropas fran execute_code handler ---

def serve_rpc(
    read_stream,       # child.stdout
    write_stream,      # child.stdin
    engine,            # PermissionEngine
    max_calls: int = 50,
    blocked_tools: set | None = None,
) -> str:
    """Las ToolRequest fran child, anropa tools via PermissionEngine, skicka ToolResponse.
    Returnerar sista stdout fran scriptet (captured via print)."""
    if blocked_tools is None:
        blocked_tools = set()
    from ..tools import registry as reg
    tool_count = 0
    script_output: list[str] = []
    for line in read_stream:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            script_output.append(line)  # inte JSON -> script-output
            continue
        if msg.get("type") != "request":
            script_output.append(line)
            continue
        tool_count += 1
        if tool_count > max_calls:
            resp = {"type": "response", "id": msg.get("id", 0), "result": "", "error": "max tool calls exceeded"}
            write_stream.write(json.dumps(resp, ensure_ascii=False) + "\n")
            write_stream.flush()
            break
        tool = msg.get("tool", "")
        args = msg.get("args", {})
        if tool in blocked_tools:
            resp = {"type": "response", "id": msg.get("id", 0), "result": "", "error": f"tool '{tool}' ar blockerad i execute_code"}
        else:
            decision = engine.classify(tool, args)
            if decision.risk.value == "blocked":
                resp = {"type": "response", "id": msg.get("id", 0), "result": "", "error": decision.reason}
            else:
                try:
                    result = reg.call(tool, args)
                    resp = {"type": "response", "id": msg.get("id", 0), "result": result, "error": None}
                except Exception as e:
                    resp = {"type": "response", "id": msg.get("id", 0), "result": "", "error": str(e)}
        write_stream.write(json.dumps(resp, ensure_ascii=False) + "\n")
        write_stream.flush()
    return "\n".join(script_output)
