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
