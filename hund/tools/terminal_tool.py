"""Terminal tool — run commands, workspace-confined cwd, destructive patterns flagged.

SECURITY: destructive patterns flagged (dispatch asks/denies based on risk).
cwd is locked to workspace. Timeout 60s. Output truncated.

Returns ToolResult so that to_llm_text() can relativize user-granted paths before redaction.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .types import (
    ToolKind,
    ToolResult,
    create_success_result,
)

DESTRUCTIVE_PATTERNS = (
    "rm -rf",
    "rmdir /s",
    "del /s",
    "format ",
    "shutdown",
    "reg delete",
    "diskpart",
    ":(){:|:&};:",
)


def is_destructive(command: str) -> bool:
    low = command.lower()
    return any(pat in low for pat in DESTRUCTIVE_PATTERNS)


def _extract_common_path_root(text: str) -> str | None:
    """Detect a common root directory from absolute Windows paths in terminal output.

    Scans for ``C:\\...`` or ``C:/...`` patterns, groups by drive letter,
    finds the longest common prefix at *path-component* granularity (using
    ``PureWindowsPath`` — no filesystem access), and returns the root directory
    path.  Requires at least two paths on the same drive.
    """
    pat = re.compile(r"([A-Za-z]:[\\/][^\s\"'`<>*?|(){}\[\]\r\n,;]+)")
    matches = pat.findall(text)
    if len(matches) < 2:
        return None

    from pathlib import PureWindowsPath

    # Convert each match to a tuple of path parts (no filesystem access)
    all_parts: list[tuple[str, ...]] = []
    for m in matches:
        try:
            p = PureWindowsPath(m)
            all_parts.append(p.parts)
        except Exception:
            continue

    if len(all_parts) < 2:
        return None

    # Group by drive letter (upper-cased)
    drives: dict[str, list[tuple[str, ...]]] = {}
    for parts in all_parts:
        drive = parts[0].rstrip("\\").upper()
        drives.setdefault(drive, []).append(parts)

    best_root: str | None = None
    best_count = 0

    for drive, group in drives.items():
        if len(group) < 2:
            continue
        # Find common prefix length (in parts, not characters)
        prefix_parts = group[0]
        for p in group[1:]:
            i = 0
            while i < len(prefix_parts) and i < len(p) and prefix_parts[i].lower() == p[i].lower():
                i += 1
            prefix_parts = prefix_parts[:i]
        if len(prefix_parts) < 2:  # Need at least drive + one directory
            continue
        root = "\\".join(prefix_parts)
        # Normalize: parts[0] is 'C:\\' with trailing backslash; joining with
        # '\\' creates 'C:\\\\Users...' — strip the extra backslash after the drive.
        root = root.replace("\\\\", "\\")
        count = len(group)
        if count > best_count:
            best_count = count
            best_root = root

    return best_root


def make_handler(workspace: Path) -> dict:
    ws = workspace.resolve()

    def run_terminal(args: dict) -> ToolResult:
        command = args["command"]
        timeout = min(int(args.get("timeout", 60)), 120)
        raw_cwd = args.get("cwd")

        target_cwd = ws
        if raw_cwd:
            candidate = (ws / raw_cwd).resolve()
            try:
                candidate.relative_to(ws)
            except ValueError:
                return create_success_result(
                    ToolKind.TEXT,
                    f"[exit 1]\nError: cwd '{raw_cwd}' is outside workspace root.",
                )
            if not candidate.exists() or not candidate.is_dir():
                return create_success_result(
                    ToolKind.TEXT,
                    f"[exit 1]\nError: cwd '{raw_cwd}' does not exist or is not a directory.",
                )
            target_cwd = candidate

        try:
            sub_env = dict(os.environ)
            sub_env["PYTHONIOENCODING"] = "utf-8"
            sub_env["PYTHONUTF8"] = "1"
            proc = subprocess.run(
                command,
                cwd=str(target_cwd),
                shell=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=sub_env,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            body = f"[exit {proc.returncode}]\n{out[:20000]}"
            # Detect common path root in output and relativize before redaction
            root = _extract_common_path_root(body)
            metadata = {"target_root": root} if root else {}
            return create_success_result(ToolKind.TEXT, body, metadata=metadata)
        except subprocess.TimeoutExpired:
            return create_success_result(
                ToolKind.TEXT,
                f"[exit 124]\nCommand timed out after {timeout}s",
            )
        except Exception as e:
            return create_success_result(
                ToolKind.TEXT,
                f"[exit 1]\nError: {e}",
            )

    return {"terminal": run_terminal}
