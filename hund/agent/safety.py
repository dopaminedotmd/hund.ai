"""Permission Engine — Hunds Trusted Computing Base (TCB).

SECURITY-INVARIANT (testas, får ej brytas):
  Denna modul + redactor + updater utgör TCB. Den får INTE ändras av
  self-improvement-loopen — ens via admin-gate. TCB uppdateras ENDAST via
  signerad release. Spärrar ligger i KOD, inte i agentens systemprompt.

Riskklasser (från HUND_SECURITY_UPDATE_ROLLBACK + review):
  SAFE       — läsa, lista, systeminfo               -> auto-tillåtet
  WRITE      — skapa/ändra fil i workspace           -> kräver rapport+backup
  CONFIRM    — installera paket, ändra config, build -> fråga användare
  DANGEROUS  — radera, flytta, credentials, system   -> explicit OK var gång
  BLOCKED    — exfiltrera secrets, kringgå safety,
               självpublicera update, skriv utanför workspace -> ALDRIG
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


_TERMINAL_BLOCKLIST = [
    r"\brm\s+-rf\s+/",           # rm -rf /
    r"\bformat\b.*\b[A-Z]:",     # format C:
    r"\bdel\s+/[sS]\s+/[qQ]",    # del /s /q (force delete)
    r"\bInvoke-Expression\b",    # PowerShell iex
    r"\biex\b",                  # PowerShell iex alias
    r":\(\)\s*\{",               # fork bomb
    r"\bshutdown\b",             # shutdown
    r"\bmkfs\b",                 # mkfs.*
    r"\bdd\s+if=",               # dd if=/dev/...
    r"\bwget.*\|.*sh\b",         # curl/wget | sh
    r"\bcurl.*\|.*sh\b",
]


class RiskLevel(str, Enum):
    SAFE = "safe"
    WRITE = "write"
    CONFIRM = "confirm"
    DANGEROUS = "dangerous"
    BLOCKED = "blocked"


# Verktyg -> basrisk. Args kan höja (t.ex. sökväg utanför workspace).
_TOOL_BASE_RISK: dict[str, RiskLevel] = {
    "read_file": RiskLevel.SAFE,
    "search_files": RiskLevel.SAFE,
    "write_file": RiskLevel.WRITE,
    "terminal": RiskLevel.CONFIRM,
    "delete_file": RiskLevel.DANGEROUS,
    "execute_code": RiskLevel.CONFIRM,
    "delegate_task": RiskLevel.CONFIRM,
}

_HUND_ROOT = Path(__file__).resolve().parent.parent  # hund/ katalogen

TCB_FILES = {
    "hund/agent/safety.py",
    "hund/agent/tool_dispatch.py",
    "hund/agent/loop.py",
    "hund/learning/redactor.py",
    "hund/main.py",
}

TCB_DIRS = {
    "hund/updater",
}

_TCB_ABS_FILES = {(_HUND_ROOT / f).resolve() for f in TCB_FILES}
_TCB_ABS_DIRS = [(_HUND_ROOT / d).resolve() for d in TCB_DIRS]


@dataclass
class Decision:
    risk: RiskLevel
    allowed: bool
    reason: str = ""


class PermissionEngine:
    """Kodad, hård permission-gate. Omutbar via prompt."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).resolve()

    def _is_blocked(self, tool: str, args: dict) -> str | None:
        """Returnera blockorsak eller None."""
        # 1. Självpublicering / update-manipulation = alltid blockerat.
        if tool in {"self_update", "apply_update", "modify_tcb"}:
            return "Hund får aldrig självpublicera uppdateringar (TCB-skydd)."
        if tool in {"execute_code", "delegate_task", "memory", "self_update", "apply_update", "modify_tcb"}:
            return f"Tool '{tool}' ar blockerat for subagents (TCB-skydd)."
        # 2. Skriv utanför workspace = blockerat (workspace-confined default).
        target = args.get("path") or args.get("cwd")
        if target and tool in {"write_file", "delete_file"}:
            try:
                resolved = (self.workspace_root / target).resolve()
                rel = resolved.relative_to(self.workspace_root).as_posix()
            except (ValueError, OSError):
                return (
                    f"Skrivning utanför workspace ({self.workspace_root}) "
                    f"är blockerat som default."
                )
            
            # 3. Skrivning till TCB-filer / TCB-kataloger = blockerat.
            # Dual check: relativ sokvag (workspace = hund-repo) ELLER
            # absolut sokvag (workspace = nagon annanstans).
            if rel in TCB_FILES or resolved in _TCB_ABS_FILES:
                return f"Skrivning till TCB-fil ({rel}) ar blockerad (TCB-skydd)."
            for tcb_dir in TCB_DIRS:
                if rel.startswith(tcb_dir + "/"):
                    return f"Skrivning till TCB-katalog ({rel}) ar blockerad (TCB-skydd)."
            for tcb_abs_dir in _TCB_ABS_DIRS:
                if resolved == tcb_abs_dir or tcb_abs_dir in resolved.parents:
                    return f"Skrivning till TCB-katalog ({rel}) ar blockerad (TCB-skydd)."
        # 4. Terminal-kommandon mot blocklistan.
        if tool == "terminal":
            cmd = args.get("command", "")
            for pattern in _TERMINAL_BLOCKLIST:
                if re.search(pattern, cmd, re.IGNORECASE):
                    return f"Terminal-kommando blockerat (matchar '{pattern}')."
        return None

    def classify(self, tool: str, args: dict | None = None) -> Decision:
        args = args or {}
        blocked_reason = self._is_blocked(tool, args)
        if blocked_reason:
            return Decision(RiskLevel.BLOCKED, allowed=False, reason=blocked_reason)
        base = _TOOL_BASE_RISK.get(tool, RiskLevel.CONFIRM)  # okänd tool = confirm
        allowed = base == RiskLevel.SAFE
        return Decision(base, allowed=allowed, reason=f"base risk for {tool}")
