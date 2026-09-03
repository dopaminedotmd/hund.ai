"""Terminal tool — run commands, workspace-confined cwd, destructive patterns flagged.

SECURITY: destructive patterns flagged (dispatch asks/denies based on risk).
cwd is locked to workspace. Timeout 60s. Output truncated.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

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


def make_handler(workspace: Path) -> dict:
    ws = workspace.resolve()

    def run_terminal(args: dict) -> str:
        command = args["command"]
        timeout = min(int(args.get("timeout", 60)), 120)
        raw_cwd = args.get("cwd")

        target_cwd = ws
        if raw_cwd:
            candidate = (ws / raw_cwd).resolve()
            try:
                candidate.relative_to(ws)
            except ValueError:
                return f"[exit 1]\nError: cwd '{raw_cwd}' is outside workspace root."
            if not candidate.exists() or not candidate.is_dir():
                return f"[exit 1]\nError: cwd '{raw_cwd}' does not exist or is not a directory."
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
            return f"[exit {proc.returncode}]\n{out[:20000]}"
        except subprocess.TimeoutExpired:
            return f"[exit 124]\nCommand timed out after {timeout}s"
        except Exception as e:
            return f"[exit 1]\nError: {e}"

    return {"terminal": run_terminal}
