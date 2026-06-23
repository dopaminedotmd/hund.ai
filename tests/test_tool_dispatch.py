"""Tool-dispatch — bevisar säkerhetscirkeln kring tool-anrop."""
from __future__ import annotations

import io

from rich.console import Console

from hund.agent.safety import PermissionEngine
from hund.agent.tool_dispatch import dispatch_tool_call
from hund.tools import registry
from hund.tools.default_tools import register_defaults


def _console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, width=200)


def _tc(name: str, args: str, tc_id: str = "1") -> dict:
    return {"id": tc_id, "type": "function", "function": {"name": name, "arguments": args}}


def test_safe_tool_runs_auto(tmp_path):
    register_defaults(tmp_path)
    (tmp_path / "hello.md").write_text("x", encoding="utf-8")
    out = dispatch_tool_call(
        _tc("search_files", '{"pattern": "*.md"}'),
        PermissionEngine(tmp_path),
        _console(),
    )
    assert "hello.md" in out


def test_write_declined_noninteractive(tmp_path):
    register_defaults(tmp_path)
    out = dispatch_tool_call(
        _tc("write_file", '{"path": "x.txt", "content": "y"}'),
        PermissionEngine(tmp_path),
        _console(),
        noninteractive=True,
    )
    assert out.startswith("[declined")


def test_blocked_self_update_never_runs(tmp_path):
    register_defaults(tmp_path)
    out = dispatch_tool_call(
        _tc("self_update", "{}"),
        PermissionEngine(tmp_path),
        _console(),
        noninteractive=False,
    )
    assert out.startswith("[blocked")


def test_terminal_outside_pattern_flagged(tmp_path):
    from hund.tools.terminal_tool import is_destructive

    assert is_destructive("rm -rf /")
    assert not is_destructive("ls -la")


def test_web_tools_registration(tmp_path):
    register_defaults(tmp_path)
    search_tool = registry.get("web_search")
    extract_tool = registry.get("web_extract")
    
    assert search_tool is not None
    assert search_tool.base_risk == "safe"
    assert extract_tool is not None
    assert extract_tool.base_risk == "safe"

