"""execute_code — agenten skriver Python-script som anropar Hunds tools via RPC."""
from __future__ import annotations
import subprocess, tempfile, os, sys, textwrap, time

MAX_TOOL_CALLS = 50
MAX_TIMEOUT = 300      # 5 minuter
MAX_STDOUT = 50_000
RPC_CLIENT_STUB = '''
import json, sys
def call_tool(tool, args=None):
    args = args or {}
    req = {"type": "request", "id": 1, "tool": tool, "args": args}
    sys.stdout.write(json.dumps(req, ensure_ascii=False) + "\\n")
    sys.stdout.flush()
    line = sys.stdin.readline()
    if not line:
        return "[error] ingen response"
    try:
        resp = json.loads(line)
    except json.JSONDecodeError:
        return f"[error] invalid JSON: {line[:100]}"
    if resp.get("error"):
        return f"[error] {resp['error']}"
    return resp.get("result", "")
'''

BLOCKED_TOOLS = {
    "execute_code", "delegate_task", "memory", "self_update", "apply_update",
    "modify_tcb", "web_open", "web_extract", "web_search",
}

def run_code(args: dict) -> str:
    """Kor Python-script i subprocess med RPC-access till Hunds tools."""
    code = args.get("code", "")
    if not code:
        return "[error] 'code' parameter saknas"
    # Inject RPC-client fore scriptet
    full_code = RPC_CLIENT_STUB + "\n" + code
    # Skriv till temp-fil (undvik escaping-problem)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(full_code)
        tmp_path = f.name
    try:
        python_exe = sys.executable  # samma Python som Hund
        proc = subprocess.Popen(
            [python_exe, tmp_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        from . import registry
        from ..agent.rpc import serve_rpc
        from ..agent.safety import PermissionEngine
        engine = PermissionEngine()
        stdout_result = serve_rpc(
            read_stream=proc.stdout,
            write_stream=proc.stdin,
            engine=engine,
            max_calls=MAX_TOOL_CALLS,
            blocked_tools=BLOCKED_TOOLS,
        )
        try:
            proc.wait(timeout=MAX_TIMEOUT)
        except subprocess.TimeoutExpired:
            # Graceful shutdown: terminate first (WM_CLOSE on Windows),
            # then force-kill only if the process doesn't exit within 3s.
            # This avoids orphaned temp files and SQLite lock corruption.
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            return "[error] execute_code timeout (300s)"
        stderr_text = proc.stderr.read()
        result = stdout_result or "(inget output)"
        if stderr_text:
            result += f"\n[stderr]\n{stderr_text}"
        if len(result) > MAX_STDOUT:
            result = result[:MAX_STDOUT] + "\n[TRUNCATD — output oversteg 50KB]"
        return result
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
