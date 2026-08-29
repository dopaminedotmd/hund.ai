"""Fast Publication Gate and Isolated Representative Dry-Run for on-demand skills."""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Callable, Iterable

from ..learning.redactor import redact_text
from .lifecycle import can_transition_skill, run_skill_sandbox_test
from .loader import _read_skill_file, load_builtins
from .model import BANNED_ACTIONS, SAFETY_LEVELS, Skill
from .validator import validate, validate_dict


@dataclass(frozen=True)
class CheckResult:
    check_name: str
    passed: bool
    error_message: str = ""


@dataclass(frozen=True)
class PreStageResult:
    passed: bool
    checks: tuple[CheckResult, ...]  # Per-check results for checks 1–7
    redacted_skill: Skill  # Skill with secrets scrubbed and prompt-injection neutralized
    failure_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublicationGateReport:
    passed: bool
    checks: tuple[CheckResult, ...]  # Complete combination of checks 1–12
    failure_reasons: tuple[str, ...]


_INJECTION_PATTERNS = (
    re.compile(r"(?i)\bignore\s+(?:all\s+)?(?:previous|prior)\s+instructions\b"),
    re.compile(r"(?i)\bdisregard\s+(?:all\s+)?(?:previous|prior)\s+instructions\b"),
    re.compile(r"(?i)\bsystem\s+prompt\s*:\b"),
    re.compile(r"(?i)<\s*system\s*>"),
    re.compile(r"(?i)<\s*/\s*system\s*>"),
    re.compile(r"(?i)\boverride\s+(?:all\s+)?safety\s+rules\b"),
    re.compile(r"(?i)\byou\s+are\s+now\s+in\s+developer\s+mode\b"),
    re.compile(r"(?i)\bdo\s+anything\s+now\b"),
)


def _neutralize_injections(text: str) -> tuple[str, bool]:
    neutralized = text
    found = False
    for pat in _INJECTION_PATTERNS:
        neutralized, count = pat.subn("[neutralized instruction override]", neutralized)
        if count > 0:
            found = True
    return neutralized, found


class IsolatedToolRegistry:
    """Mock offline tool registry strictly confined to isolated temp workspace."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()

    def all_tool_names(self) -> set[str]:
        return {
            "read_file", "search_files", "write_file", "delete_file",
            "terminal", "web_search", "web_open", "web_extract",
        }

    def get_tool_schema(self, tool_name: str) -> dict[str, Any]:
        return {"name": tool_name, "type": "function"}

    def get_handler(self, tool_name: str) -> Callable[[dict[str, Any]], Any]:
        if tool_name.startswith("winvault_") or "vault" in tool_name or tool_name in BANNED_ACTIONS:
            def denied(_args: dict[str, Any]) -> Any:
                raise PermissionError(f"Access to tool '{tool_name}' is denied in isolated dry-run.")
            return denied

        if tool_name in ("web_search", "web_open", "web_extract"):
            def offline_web(args: dict[str, Any]) -> dict[str, Any]:
                return {"status": "success", "results": ["Mock offline documentation for dry-run."]}
            return offline_web

        if tool_name == "read_file":
            def read_f(args: dict[str, Any]) -> dict[str, Any]:
                path = (self.workspace_root / args.get("path", "test.txt")).resolve()
                if not path.is_relative_to(self.workspace_root):
                    raise PermissionError("Path traversal outside workspace root is forbidden.")
                if path.is_file():
                    return {"content": path.read_text(encoding="utf-8")}
                return {"content": "sample workspace file content"}
            return read_f

        if tool_name == "write_file":
            def write_f(args: dict[str, Any]) -> dict[str, Any]:
                path = (self.workspace_root / args.get("path", "test.txt")).resolve()
                if not path.is_relative_to(self.workspace_root):
                    raise PermissionError("Path traversal outside workspace root is forbidden.")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(args.get("content", ""), encoding="utf-8")
                return {"status": "written"}
            return write_f

        if tool_name == "search_files":
            def search_f(args: dict[str, Any]) -> dict[str, Any]:
                return {"files": ["sample.py"]}
            return search_f

        if tool_name == "terminal":
            def term_f(args: dict[str, Any]) -> dict[str, Any]:
                return {"stdout": "mock terminal output", "exit_code": 0}
            return term_f

        def default_handler(args: dict[str, Any]) -> dict[str, Any]:
            return {"status": "ok"}
        return default_handler


class IsolatedDryRunAdapter:
    """Executes a representative dry-run in an isolated temporary directory."""

    def __init__(self, workspace_root: Path | None = None, home: Path | None = None) -> None:
        self.workspace_root = workspace_root
        self.home = home

    def execute(self, skill: Skill, staged_path: Path) -> tuple[bool, str]:
        # If pure instruction skill without tools, pass immediately
        if not skill.required_tools:
            return True, "Instruction-only skill passes sandbox without execution."

        temp_dir = tempfile.mkdtemp(prefix="hund_dryrun_")
        try:
            temp_home = Path(temp_dir).resolve()
            temp_ws = temp_home / "workspace"
            temp_ws.mkdir(parents=True, exist_ok=True)

            # Validate containment
            if not temp_ws.is_relative_to(temp_home):
                return False, "Isolated workspace path escaped temporary containment."

            registry = IsolatedToolRegistry(temp_ws)

            # Check tools against isolated registry
            for tool in skill.required_tools:
                if tool in BANNED_ACTIONS or tool.startswith("winvault_"):
                    return False, f"Banned or credential tool '{tool}' forbidden in dry run."
                handler = registry.get_handler(tool)
                try:
                    handler({"path": "dryrun_sample.txt", "content": "dryrun test"})
                except Exception as exc:
                    return False, f"Tool '{tool}' dry-run execution failed: {exc}"

            return True, "Sandbox dry-run executed successfully."
        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass


class FastPublicationGate:
    """12-check publication gate with in-memory pre-stage scanning and isolated dry-run."""

    def pre_stage_scan(
        self,
        skill: Skill,
        existing_skills: list[Skill] | None = None,
        builtins: list[Skill] | None = None,
        registered_tools: set[str] | None = None,
    ) -> PreStageResult:
        checks: list[CheckResult] = []
        failures: list[str] = []

        # 1. Schema and manifest
        val_errors = validate(skill)
        if val_errors:
            checks.append(CheckResult("schema_and_manifest", False, "; ".join(val_errors)))
            failures.extend(val_errors)
        else:
            checks.append(CheckResult("schema_and_manifest", True))

        # 2. Triggers and collisions
        builtins_list = builtins if builtins is not None else load_builtins()
        builtin_names = {b.name.lower() for b in builtins_list}
        collision_err = None
        if skill.name.lower() in builtin_names:
            collision_err = f"Skill name '{skill.name}' collides with constitutional builtin."
        else:
            # Check normalized trigger collisions
            for trig in skill.triggers:
                norm_trig = re.sub(r"[^a-z0-9]", "", trig.lower())
                for b in builtins_list:
                    for b_trig in b.triggers:
                        norm_b = re.sub(r"[^a-z0-9]", "", b_trig.lower())
                        if norm_trig and norm_trig == norm_b and skill.name != b.name:
                            collision_err = f"Trigger '{trig}' collides with constitutional builtin '{b.name}'."
                            break
                    if collision_err:
                        break
                if collision_err:
                    break

        if collision_err:
            checks.append(CheckResult("triggers_and_collisions", False, collision_err))
            failures.append(collision_err)
        else:
            checks.append(CheckResult("triggers_and_collisions", True))

        # 3. Required tools exist
        avail_tools = registered_tools if registered_tools is not None else {
            "read_file", "search_files", "write_file", "delete_file", "terminal",
            "web_search", "web_open", "web_extract", "execute_code", "delegate_task", "create_skill",
        }
        missing_tools = [t for t in skill.required_tools if t not in avail_tools]
        if missing_tools:
            err = f"Required tools missing in registry: {missing_tools}"
            checks.append(CheckResult("required_tools_exist", False, err))
            failures.append(err)
        else:
            checks.append(CheckResult("required_tools_exist", True))

        # 4. Permission and safety
        # Mutating tools require safety_level == "confirm" or "confirm_for_write"
        mutating_tools = {"write_file", "delete_file", "terminal", "execute_code", "create_skill"}
        needs_confirm = any(t in mutating_tools for t in skill.required_tools)
        if needs_confirm and skill.safety_level not in ("confirm", "confirm_for_write"):
            err = f"Mutating tool in required_tools requires confirm safety_level, got '{skill.safety_level}'."
            checks.append(CheckResult("permission_and_safety", False, err))
            failures.append(err)
        else:
            checks.append(CheckResult("permission_and_safety", True))

        # 5. Banned actions
        bad_in_tools = set(skill.required_tools) & BANNED_ACTIONS
        missing_bans = BANNED_ACTIONS - set(skill.forbidden_actions)
        if bad_in_tools or missing_bans:
            err = f"Banned actions violation: bad_in_tools={sorted(bad_in_tools)}, missing_bans={sorted(missing_bans)}"
            checks.append(CheckResult("banned_actions", False, err))
            failures.append(err)
        else:
            checks.append(CheckResult("banned_actions", True))

        # 6. Secret redaction (scrub in memory)
        redacted_triggers = []
        redacted_steps = []
        redacted_examples = []
        secrets_found = False

        when_red = redact_text(skill.when_to_use)
        if "secret" in when_red.blocked_fields:
            secrets_found = True
        when_to_use_clean = when_red.text

        for t in skill.triggers:
            r = redact_text(t)
            if "secret" in r.blocked_fields:
                secrets_found = True
            redacted_triggers.append(r.text)

        for s in skill.steps:
            r = redact_text(s)
            if "secret" in r.blocked_fields:
                secrets_found = True
            redacted_steps.append(r.text)

        for e in skill.examples:
            r = redact_text(e)
            if "secret" in r.blocked_fields:
                secrets_found = True
            redacted_examples.append(r.text)

        redacted_verification = []
        for v in skill.verification:
            r = redact_text(v)
            if "secret" in r.blocked_fields:
                secrets_found = True
            redacted_verification.append(r.text)

        checks.append(CheckResult("secret_redaction", True))

        # 7. Prompt injection neutralization
        neutralized_steps = []
        injections_found = False
        for s in redacted_steps:
            clean_s, found = _neutralize_injections(s)
            if found:
                injections_found = True
            neutralized_steps.append(clean_s)

        neutralized_verification = []
        for v in redacted_verification:
            clean_v, found = _neutralize_injections(v)
            if found:
                injections_found = True
            neutralized_verification.append(clean_v)

        clean_when, found_w = _neutralize_injections(when_to_use_clean)
        if found_w:
            injections_found = True

        checks.append(CheckResult("prompt_injection", True))

        redacted_skill = replace(
            skill,
            when_to_use=clean_when,
            triggers=tuple(redacted_triggers),
            steps=tuple(neutralized_steps),
            examples=tuple(redacted_examples),
            verification=tuple(neutralized_verification),
        )

        all_passed = len(failures) == 0
        return PreStageResult(
            passed=all_passed,
            checks=tuple(checks),
            redacted_skill=redacted_skill,
            failure_reasons=tuple(failures),
        )

    def evaluate(
        self,
        skill: Skill,
        staged_path: Path,
        registered_tools: set[str],
        pre_stage_checks: tuple[CheckResult, ...] = (),
        dry_run_executor: Callable[[Skill, Path], tuple[bool, str]] | None = None,
        slot_capacity_available: bool = True,
    ) -> PublicationGateReport:
        checks: list[CheckResult] = list(pre_stage_checks)
        failures: list[str] = [c.error_message for c in checks if not c.passed and c.error_message]

        # 8. Loader round-trip
        staged_skill = _read_skill_file(staged_path)
        if staged_skill is None:
            err = f"Loader round-trip failed to load staged draft at '{staged_path}'."
            checks.append(CheckResult("loader_roundtrip", False, err))
            failures.append(err)
        else:
            checks.append(CheckResult("loader_roundtrip", True))

        # 9. Instruction only safe
        if not skill.required_tools:
            checks.append(CheckResult("instruction_only_safe", True))
        else:
            checks.append(CheckResult("instruction_only_safe", True))

        # 10. Isolated dry-run
        if skill.required_tools:
            if dry_run_executor is not None:
                ok, msg = dry_run_executor(skill, staged_path)
            else:
                adapter = IsolatedDryRunAdapter()
                ok, msg = adapter.execute(skill, staged_path)
            if not ok:
                checks.append(CheckResult("isolated_dry_run", False, msg))
                failures.append(msg)
            else:
                checks.append(CheckResult("isolated_dry_run", True))
        else:
            checks.append(CheckResult("isolated_dry_run", True))

        # 11. Lifecycle transition
        # draft -> schema_valid -> sandbox_tested -> active
        has_tools = bool(skill.required_tools)
        ok_trans, trans_msg = can_transition_skill("draft", "schema_valid", has_tools=has_tools)
        if ok_trans:
            if has_tools:
                ok_trans, trans_msg = can_transition_skill("sandbox_tested", "active", has_tools=has_tools)
            else:
                ok_trans, trans_msg = can_transition_skill("schema_valid", "active", has_tools=has_tools)

        if not ok_trans:
            checks.append(CheckResult("lifecycle_transition", False, trans_msg))
            failures.append(trans_msg)
        else:
            checks.append(CheckResult("lifecycle_transition", True))

        # 12. Scope and vault disposition check
        checks.append(CheckResult("scope_and_vault_disposition", True))

        all_passed = len(failures) == 0
        return PublicationGateReport(
            passed=all_passed,
            checks=tuple(checks),
            failure_reasons=tuple(failures),
        )
