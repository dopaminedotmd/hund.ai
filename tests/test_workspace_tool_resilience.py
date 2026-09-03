"""Tests for Bug 2a: Workspace tool resilience, instructive out-of-workspace errors, and path relativization."""
from __future__ import annotations

from pathlib import Path
import pytest

from hund.tools.file_tool import make_handlers
from hund.tools.types import (
    ToolKind,
    ToolResult,
    ToolStatus,
    create_success_result,
    relativize_user_granted_path,
)
from hund.tools import default_tools, registry


def test_read_file_outside_workspace_returns_instructive_error(tmp_path: Path):
    """read_file outside workspace returns instructive error pointing to terminal / workspace switch."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target_file = outside / "gradle.properties"
    target_file.write_text("minecraft_version=26.2\n", encoding="utf-8")

    handlers = make_handlers(ws)
    read_file = handlers["read_file"]

    # Call with absolute path outside workspace
    result = read_file({"path": str(target_file)})
    assert result.startswith("[error] path outside workspace; use the terminal with the user-provided absolute path or request workspace switch:")
    assert str(target_file) in result


def test_relativize_user_granted_path_preserves_legibility_under_root():
    """Paths strictly under user-granted target_root are normalized to relative paths before redaction."""
    target_root = r"C:\Users\William\minecraftmod-r.i.p"
    payload = (
        r"C:\Users\William\minecraftmod-r.i.p\src\Main.java" "\n"
        r"C:\Users\William\minecraftmod-r.i.p\gradle.properties"
    )

    relativized = relativize_user_granted_path(payload, target_root)
    assert r".\src\Main.java" in relativized or "./src/Main.java" in relativized
    assert r".\gradle.properties" in relativized or "./gradle.properties" in relativized
    assert r"C:\Users\William" not in relativized

    # When rendered via ToolResult.to_llm_text, filenames remain visible (not redacted to [REDACTED:path])
    res = create_success_result(
        ToolKind.TEXT,
        payload,
        metadata={"target_root": target_root},
    )
    rendered = res.to_llm_text()
    assert "Main.java" in rendered
    assert "gradle.properties" in rendered
    assert "[REDACTED:path]" not in rendered


def test_relativize_user_granted_path_strict_segment_matching_rejects_evil_sibling():
    """Strict segment matching ensures sibling folders with shared prefixes are NOT relativized and remain redacted."""
    target_root = r"C:\Users\William\minecraftmod-r.i.p"
    payload = (
        r"C:\Users\William\minecraftmod-r.i.p-evil\malicious.txt" "\n"
        r"C:\Users\William\secret.key" "\n"
        r"C:\Users\William\minecraftmod-r.i.p\src\Main.java"
    )

    relativized = relativize_user_granted_path(payload, target_root)
    # The evil sibling must NOT be relativized
    assert r"C:\Users\William\minecraftmod-r.i.p-evil\malicious.txt" in relativized
    assert r"C:\Users\William\secret.key" in relativized
    # The genuine child MUST be relativized
    assert "Main.java" in relativized
    assert r"C:\Users\William\minecraftmod-r.i.p\src\Main.java" not in relativized

    # When passed through ToolResult.to_llm_text, the evil sibling and secret are redacted to [REDACTED:path]
    res = create_success_result(
        ToolKind.TEXT,
        payload,
        metadata={"target_root": target_root},
    )
    rendered = res.to_llm_text()
    assert "Main.java" in rendered
    assert "malicious.txt" not in rendered  # redacted
    assert "secret.key" not in rendered     # redacted
    assert "[REDACTED:path]" in rendered    # evil sibling & secret both got redacted


def test_terminal_tool_description_recommends_python_or_find(tmp_path: Path):
    """Terminal tool description advises preferring python or find over cmd for /r to prevent %%f escaping bugs."""
    default_tools.register_defaults(tmp_path)
    tool = registry.get("terminal")
    assert tool is not None
    assert "prefer python or find over cmd for /r; cmd doubles % in batch contexts" in tool.description.lower()

def test_extract_common_path_root_detects_minecraftmod():
    """_extract_common_path_root finds common root from multiple paths in terminal output."""
    from hund.tools.terminal_tool import _extract_common_path_root

    output = (
        r" Directory of C:\Users\William\minecraftmod-r.i.p" "\n"
        r"2026-09-03  18:46    <DIR>          ." "\n"
        r"C:\Users\William\minecraftmod-r.i.p\src\Main.java" "\n"
        r"C:\Users\William\minecraftmod-r.i.p\gradle.properties" "\n"
        r"C:\Users\William\minecraftmod-r.i.p\build.gradle"
    )
    root = _extract_common_path_root(output)
    assert root is not None
    assert root.rstrip("\\/") == r"C:\Users\William\minecraftmod-r.i.p"


def test_extract_common_path_root_none_on_single_path():
    """Single absolute path should not produce a root (no common prefix needed)."""
    from hund.tools.terminal_tool import _extract_common_path_root

    output = r"C:\Users\William\some_file.txt"
    root = _extract_common_path_root(output)
    assert root is None


def test_extract_common_path_root_mixed_drives():
    """Paths across different drives are grouped; highest-count group wins."""
    from hund.tools.terminal_tool import _extract_common_path_root

    output = (
        r"E:\backup\file1.txt" "\n"
        r"E:\backup\sub\file2.txt" "\n"
        r"C:\Windows\win.ini"
    )
    root = _extract_common_path_root(output)
    assert root is not None
    # E:\backup has 2 entries, C:\Windows has 1 -> E:\backup wins
    assert root.rstrip("\\/") == r"E:\backup"


def test_terminal_returns_toolresult_on_normal_run(tmp_path: Path):
    """Terminal handler returns a ToolResult, enabling metadata.target_root for relativization."""
    from hund.tools.terminal_tool import make_handler
    from hund.tools.types import ToolKind, ToolStatus

    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "hello.txt").write_text("hello", encoding="utf-8")

    handlers = make_handler(ws)
    run = handlers["terminal"]
    result = run({"command": "echo hello", "timeout": 10})

    from hund.tools.types import ToolResult as TR
    assert isinstance(result, TR)
    assert result.status == ToolStatus.SUCCESS
    assert result.kind == ToolKind.TEXT
    assert "hello" in result.payload


def test_terminal_metadata_target_root_set_when_paths_detected(tmp_path: Path):
    """Terminal output with multiple absolute paths sets metadata.target_root."""
    from hund.tools.terminal_tool import make_handler
    from pathlib import Path

    ws = tmp_path / "workspace"
    ws.mkdir()

    # Create a fake "external" directory
    ext = tmp_path / "ext"
    ext.mkdir()
    (ext / "a.txt").write_text("a", encoding="utf-8")
    (ext / "b.txt").write_text("b", encoding="utf-8")

    handlers = make_handler(ws)
    run = handlers["terminal"]
    # Use cmd to echo paths that look like absolute paths
    ext_str = str(ext).replace("\\", "\\\\")
    result = run({
        "command": f"echo {str(ext / 'a.txt')} && echo {str(ext / 'b.txt')}",
        "timeout": 10,
    })
    assert result.metadata is not None
    root = result.metadata.get("target_root")
    assert root is not None
    assert Path(root) == ext