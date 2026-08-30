"""Hard permission policy for Hund's Trusted Computing Base.

Model-produced tool arguments are untrusted. This module classifies the complete
action in code; prompt instructions are never treated as a security boundary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class RiskLevel(str, Enum):
    SAFE = "safe"
    WRITE = "write"
    CONFIRM = "confirm"
    DANGEROUS = "dangerous"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class Decision:
    risk: RiskLevel
    allowed: bool
    reason: str = ""
    policy_id: str = ""
    session_allowable: bool = False


_TERMINAL_BLOCKLIST: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"""\brm\s+-rf\s+(?:["']?/(?:["']?)|["']?[A-Za-z]:[\\/]?["']?)\s*$""",
            re.IGNORECASE,
        ),
        "recursive delete of a filesystem root",
    ),
    (re.compile(r"\bformat\b.*\b[A-Z]:", re.IGNORECASE), "format a drive"),
    (re.compile(r"\bdel\s+/[sS]\s+/[qQ]", re.IGNORECASE), "forced recursive delete"),
    (
        re.compile(r"\bInvoke-Expression\b|\biex\b", re.IGNORECASE),
        "dynamic PowerShell evaluation",
    ),
    (re.compile(r":\(\)\s*\{"), "fork bomb"),
    (re.compile(r"\bshutdown\b|\breboot\b", re.IGNORECASE), "shutdown or reboot"),
    (re.compile(r"\bmkfs(?:\.\w+)?\b", re.IGNORECASE), "format a filesystem"),
    (re.compile(r"\bdd\s+if=", re.IGNORECASE), "raw disk write"),
    (
        re.compile(r"\b(?:curl|wget)\b.*\|\s*(?:ba)?sh\b", re.IGNORECASE),
        "download and execute a shell script",
    ),
    (
        re.compile(r"\bStart-Process\b.*-Verb\s+RunAs", re.IGNORECASE),
        "elevated process execution",
    ),
    (
        re.compile(r"\bSet-ExecutionPolicy\b", re.IGNORECASE),
        "execution-policy modification",
    ),
    (re.compile(r"\bNew-Service\b", re.IGNORECASE), "service creation"),
    (
        re.compile(r"\b(?:iwr|Invoke-WebRequest)\b.*\.ps1", re.IGNORECASE),
        "PowerShell script download",
    ),
    (
        re.compile(r"\bAdd-MpPreference\b.*-ExclusionPath", re.IGNORECASE),
        "security exclusion",
    ),
    (
        re.compile(r"\breg\s+add\b.*\\Run\b", re.IGNORECASE),
        "registry autostart",
    ),
)

_TERMINAL_DANGEROUS_PATTERNS: tuple[
    tuple[re.Pattern[str], str, str], ...
] = (
    (
        re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
        "terminal.recursive_delete",
        "recursively delete files",
    ),
    (
        re.compile(r"\b(?:rm|del|erase|Remove-Item)\b", re.IGNORECASE),
        "terminal.delete",
        "delete files",
    ),
    (
        re.compile(r"\b(?:rmdir|rd)\b", re.IGNORECASE),
        "terminal.remove_directory",
        "remove a directory",
    ),
    (
        re.compile(
            r"\b(?:sc(?:\.exe)?\s+create|reg(?:\.exe)?\s+(?:add|delete)|"
            r"Add-MpPreference)\b",
            re.IGNORECASE,
        ),
        "terminal.system_change",
        "change system security or persistence settings",
    ),
)

_TERMINAL_CONFIRM_PATTERNS: tuple[
    tuple[re.Pattern[str], str, str, bool], ...
] = (
    (
        re.compile(r"^\s*git\s+push\b", re.IGNORECASE),
        "terminal.git_push",
        "push commits to a remote repository",
        True,
    ),
    (
        re.compile(
            r"^\s*(?:pip|pip3)\s+install\b|"
            r"^\s*(?:npm|pnpm|yarn)\s+(?:install|add|i)\b|"
            r"^\s*uv\s+(?:add|pip\s+install)\b|"
            r"^\s*cargo\s+install\b",
            re.IGNORECASE,
        ),
        "terminal.package_install",
        "install software packages",
        True,
    ),
)

_TERMINAL_SAFE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"^\s*(?:pwd|dir|ls|Get-Location|Get-ChildItem|Test-Path)"
            r"(?:\s+[^\r\n]*)?$",
            re.IGNORECASE,
        ),
        "terminal.safe.inspect",
    ),
    (
        re.compile(
            r"^\s*(?:rg|Get-Content|Select-String)(?:\s+[^\r\n]+)?$",
            re.IGNORECASE,
        ),
        "terminal.safe.read",
    ),
    (
        re.compile(
            r"^\s*git\s+(?:status|diff|log|show|rev-parse)\b[^\r\n]*$",
            re.IGNORECASE,
        ),
        "terminal.safe.git_read",
    ),
    (
        re.compile(r"^\s*git\s+branch\s+--list\b[^\r\n]*$", re.IGNORECASE),
        "terminal.safe.git_read",
    ),
    (
        re.compile(
            r"^\s*(?:hund|python|python3|pip|pip3|git|node|npm|uv)"
            r"\s+(?:--version|-V|--help|-h)\s*$",
            re.IGNORECASE,
        ),
        "terminal.safe.version",
    ),
)

_SHELL_COMPOSITION_RE = re.compile(
    r"(?:\r|\n|&&|\|\||[;|&<>]|\$\(|\x60|"
    r"\b(?:powershell|pwsh)\b[^\r\n]*\s-(?:Encoded)?Command\b|"
    r"\bcmd(?:\.exe)?\s+/[ck]\b|"
    r"\b(?:python|python3)\s+-c\b|\bnode\s+-e\b)",
    re.IGNORECASE,
)

_UNSCOPED_READ_PATH_RE = re.compile(
    r"(?:^|\s)(?:[A-Za-z]:[\\/]|\\\\|/|\.\.[\\/]|~[\\/]|"
    r"\$env:|%[A-Za-z_][A-Za-z0-9_]*%)",
    re.IGNORECASE,
)

_SENSITIVE_WRITE_BASENAME_RE = re.compile(
    r"^(?:\.env(?:\..*)?|.*(?:credential|secret|token|password|api[_-]?key).*|"
    r".*\.(?:pem|key|p12|pfx)|id_(?:rsa|dsa|ecdsa|ed25519))$",
    re.IGNORECASE,
)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----", re.IGNORECASE
)

_TOOL_BASE_RISK: dict[str, RiskLevel] = {
    "read_file": RiskLevel.SAFE,
    "search_files": RiskLevel.SAFE,
    "write_file": RiskLevel.SAFE,
    "terminal": RiskLevel.CONFIRM,
    "delete_file": RiskLevel.DANGEROUS,
    "execute_code": RiskLevel.CONFIRM,
    "delegate_task": RiskLevel.CONFIRM,
    "session_search": RiskLevel.SAFE,
    "web_search": RiskLevel.SAFE,
    "web_open": RiskLevel.SAFE,
    "web_extract": RiskLevel.SAFE,
    "cronjob": RiskLevel.CONFIRM,
    "create_skill": RiskLevel.CONFIRM,
}

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

TCB_FILES = {
    "hund/agent/safety.py",
    "hund/agent/tool_dispatch.py",
    "hund/agent/loop.py",
    "hund/agent/delegation.py",
    "hund/agent/rpc.py",
    "hund/learning/redactor.py",
    "hund/main.py",
}
TCB_DIRS = {"hund/updater"}
_TCB_ABS_FILES = {(_REPOSITORY_ROOT / item).resolve() for item in TCB_FILES}
_TCB_ABS_DIRS = [(_REPOSITORY_ROOT / item).resolve() for item in TCB_DIRS]


class PermissionEngine:
    """Classify tool calls through immutable code-level permission rules."""

    def __init__(
        self,
        workspace_root: Path | None = None,
        mode: str = "main_agent",
    ) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        valid_modes = {
            "main_agent",
            "subagent",
            "execute_code",
            "cron",
            "connector_remote",
        }
        if mode not in valid_modes:
            raise ValueError(f"Invalid execution mode: {mode}")
        self.mode = mode

    def _is_blocked(self, tool: str, args: dict[str, Any]) -> str | None:
        """Return a hard-block reason, or None when classification may continue."""
        if tool in {"self_update", "apply_update", "modify_tcb"}:
            return "Hund may never self-publish updates (TCB protection)."

        if self.mode != "main_agent" and tool in {
            "execute_code",
            "delegate_task",
            "memory",
            "self_update",
            "apply_update",
            "modify_tcb",
        }:
            return f"Tool '{tool}' is blocked in {self.mode} mode (TCB protection)."

        target = args.get("path") or args.get("cwd")
        if target and tool in {"write_file", "delete_file"}:
            if not isinstance(target, (str, Path)):
                return "Write target must be a valid path."
            try:
                resolved = (self.workspace_root / target).resolve()
                relative = resolved.relative_to(self.workspace_root).as_posix()
            except (ValueError, OSError):
                return f"Write outside workspace ({self.workspace_root}) is blocked."

            if relative in TCB_FILES or resolved in _TCB_ABS_FILES:
                return f"Write to TCB file ({relative}) is blocked."
            for directory in TCB_DIRS:
                if relative == directory or relative.startswith(directory + "/"):
                    return f"Write to TCB directory ({relative}) is blocked."
            for absolute_directory in _TCB_ABS_DIRS:
                if resolved == absolute_directory or absolute_directory in resolved.parents:
                    return f"Write to TCB directory ({relative}) is blocked."
            if (
                relative == "hund/skills/builtins"
                or relative.startswith("hund/skills/builtins/")
            ):
                return f"Write to immutable runtime skill ({relative}) is blocked."

        if tool == "terminal":
            command = args.get("command", "")
            if not isinstance(command, str) or not command.strip():
                return "Terminal command must be a non-empty string."
            for pattern, description in _TERMINAL_BLOCKLIST:
                if pattern.search(command):
                    return f"Terminal command blocked: {description}."
        return None

    @staticmethod
    def _classify_terminal_command(command: str) -> Decision:
        """Classify a complete untrusted shell command conservatively."""
        for pattern, policy_id, description in _TERMINAL_DANGEROUS_PATTERNS:
            if pattern.search(command):
                return Decision(
                    RiskLevel.DANGEROUS,
                    allowed=False,
                    reason=f"Approval required to {description}.",
                    policy_id=policy_id,
                )

        if _SHELL_COMPOSITION_RE.search(command):
            return Decision(
                RiskLevel.CONFIRM,
                allowed=False,
                reason="Compound or arbitrary shell execution requires approval.",
                policy_id="terminal.compound",
            )

        for (
            pattern,
            policy_id,
            description,
            session_allowable,
        ) in _TERMINAL_CONFIRM_PATTERNS:
            if pattern.search(command):
                return Decision(
                    RiskLevel.CONFIRM,
                    allowed=False,
                    reason=f"Approval required to {description}.",
                    policy_id=policy_id,
                    session_allowable=session_allowable,
                )

        if not _UNSCOPED_READ_PATH_RE.search(command):
            for pattern, policy_id in _TERMINAL_SAFE_PATTERNS:
                if pattern.fullmatch(command):
                    return Decision(
                        RiskLevel.SAFE,
                        allowed=True,
                        reason="Complete read-only command matched the safe policy.",
                        policy_id=policy_id,
                    )

        return Decision(
            RiskLevel.CONFIRM,
            allowed=False,
            reason="Unknown or unscoped terminal command requires approval.",
            policy_id="terminal.unknown",
        )

    @staticmethod
    def _classify_write(path: str, content: str) -> Decision:
        """Classify a workspace-confined write after path gates have passed."""
        from ..learning.redactor import redact_text

        redaction = redact_text(content)
        if "secret" in redaction.blocked_fields or _PRIVATE_KEY_RE.search(content):
            return Decision(
                RiskLevel.BLOCKED,
                allowed=False,
                reason=(
                    "Plaintext credentials or private keys cannot be written "
                    "to the workspace."
                ),
                policy_id="write_file.secret_content",
            )

        normalized = path.replace("\\", "/")
        basename = normalized.rsplit("/", 1)[-1]
        parts = tuple(part.casefold() for part in normalized.split("/") if part)
        is_ci_workflow = (
            len(parts) >= 2
            and parts[0] == ".github"
            and parts[1] == "workflows"
        )
        if _SENSITIVE_WRITE_BASENAME_RE.fullmatch(basename) or is_ci_workflow:
            return Decision(
                RiskLevel.CONFIRM,
                allowed=False,
                reason=(
                    "Writing a sensitive configuration or credential path "
                    "requires approval."
                ),
                policy_id="write_file.sensitive_path",
            )

        return Decision(
            RiskLevel.SAFE,
            allowed=True,
            reason="Ordinary write within the protected workspace.",
            policy_id="write_file.workspace",
        )

    def classify(
        self,
        tool: str,
        args: dict[str, Any] | None = None,
    ) -> Decision:
        arguments = args or {}
        blocked_reason = self._is_blocked(tool, arguments)
        if blocked_reason:
            return Decision(
                RiskLevel.BLOCKED,
                allowed=False,
                reason=blocked_reason,
                policy_id=f"{tool}.blocked",
            )

        if tool == "terminal":
            return self._classify_terminal_command(str(arguments.get("command", "")))

        if tool == "write_file":
            path = arguments.get("path")
            content = arguments.get("content")
            if (
                not isinstance(path, str)
                or not path.strip()
                or not isinstance(content, str)
            ):
                return Decision(
                    RiskLevel.BLOCKED,
                    allowed=False,
                    reason="Write path and content must be valid strings.",
                    policy_id="write_file.invalid",
                )
            return self._classify_write(path, content)

        base = _TOOL_BASE_RISK.get(tool, RiskLevel.CONFIRM)
        return Decision(
            base,
            allowed=base is RiskLevel.SAFE,
            reason=f"Base risk for {tool}.",
            policy_id=f"{tool}.base",
        )
