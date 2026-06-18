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

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


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
}


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
        # 2. Skriv utanför workspace = blockerat (workspace-confined default).
        target = args.get("path") or args.get("cwd")
        if target and tool in {"write_file", "delete_file"}:
            try:
                resolved = (self.workspace_root / target).resolve()
                resolved.relative_to(self.workspace_root)
            except (ValueError, OSError):
                return (
                    f"Skrivning utanför workspace ({self.workspace_root}) "
                    f"är blockerat som default."
                )
        return None

    def classify(self, tool: str, args: dict | None = None) -> Decision:
        args = args or {}
        blocked_reason = self._is_blocked(tool, args)
        if blocked_reason:
            return Decision(RiskLevel.BLOCKED, allowed=False, reason=blocked_reason)
        base = _TOOL_BASE_RISK.get(tool, RiskLevel.CONFIRM)  # okänd tool = confirm
        allowed = base == RiskLevel.SAFE
        return Decision(base, allowed=allowed, reason=f"base risk for {tool}")
