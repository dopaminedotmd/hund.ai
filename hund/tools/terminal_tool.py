"""Terminal tool — kör kommando, workspace-confined cwd, destructive höjs.

SECURITY: destruktiva mönster flaggas (dispatch nekar/ frågar beroende på risk).
cwd låses till workspace. Timeout 60s. Output trunkeras.
"""
from __future__ import annotations

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
        proc = subprocess.run(
            command,
            cwd=str(ws),
            shell=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return f"[exit {proc.returncode}]\n{out[:20000]}"

    return {"terminal": run_terminal}
