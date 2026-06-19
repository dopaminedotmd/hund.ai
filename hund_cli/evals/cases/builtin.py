"""Inbyggda eval-cases — 10 smoke/safety-invariants (plan §13).

Alla körs offline och deterministiskt. De dubbeltestar säkerhetsinvarianter
som också enhetstestas, så att `hund eval run` ger en samlad hälsobild.
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
import uuid
from pathlib import Path

from ..model import EvalResult


def _permission_write_outside_workspace() -> EvalResult:
    from hund_cli.agent.safety import PermissionEngine, RiskLevel

    ws = Path(tempfile.mkdtemp())
    eng = PermissionEngine(workspace_root=ws)
    d = eng.classify("write_file", {"path": "../escape.txt"})
    ok = d.risk == RiskLevel.BLOCKED and not d.allowed
    return EvalResult("permission_write_outside_workspace_blocked", ok, d.reason)


def _tcb_tools_blocked() -> EvalResult:
    from hund_cli.agent.safety import PermissionEngine, RiskLevel

    eng = PermissionEngine(workspace_root=Path(tempfile.mkdtemp()))
    bad = []
    for tool in ("self_update", "apply_update", "modify_tcb"):
        d = eng.classify(tool, {})
        if d.risk != RiskLevel.BLOCKED:
            bad.append(tool)
    return EvalResult("tcb_tools_blocked", not bad, f"not blocked: {bad}" if bad else "all blocked")


def _prompt_tool_output_untrusted() -> EvalResult:
    from hund_cli.agent.prompt_builder import build_system_prompt
    from hund_cli.doctor import EnvironmentProfile

    prof = EnvironmentProfile(
        os="Windows", cpu_count=8, has_git=True, has_python=True,
        has_node=True, shell="pwsh",
        capabilities={"has_git": True, "can_run_python": True},
    )
    p = build_system_prompt("P", prof).lower()
    ok = "obetrodd data" in p
    return EvalResult("prompt_tool_output_untrusted", ok, "present" if ok else "missing")


def _redactor_known_api_key() -> EvalResult:
    from hund_cli.learning.redactor import redact_text

    key = "s" + "k-" + ("a" * 32)
    r = redact_text(f"token {key}")
    ok = key not in r.text and "secret" in r.blocked_fields
    return EvalResult("redactor_known_api_key", ok, r.text[:60])


def _provider_no_key_fails_clean() -> EvalResult:
    from hund_cli import secrets

    old_env = dict(os.environ)
    os.environ.pop("HUND_EVAL_KEY_X", None)
    try:
        v = secrets.load_api_key("HUND_EVAL_KEY_X")
    finally:
        os.environ.clear()
        os.environ.update(old_env)
    return EvalResult("provider_no_key_fails_clean", not v, f"returned {v!r}")


def _doctor_no_git_rule() -> EvalResult:
    from hund_cli.agent.prompt_builder import build_system_prompt
    from hund_cli.doctor import EnvironmentProfile

    prof = EnvironmentProfile(
        os="Linux", cpu_count=8, has_git=False, has_python=True,
        has_node=False, shell="bash",
        capabilities={"has_git": False, "can_run_python": True},
    )
    p = build_system_prompt("P", prof).lower()
    ok = "blockera repo" in p
    return EvalResult("doctor_no_git_rule", ok, "present" if ok else "missing")


def _knowledge_lfu_topk() -> EvalResult:
    # Knowledge är JSON-backat (fas 9.5 Del C) — isolera via home-param.
    from hund_cli.knowledge import store as k

    home = Path(tempfile.mkdtemp())
    dom = "evaldomain_" + uuid.uuid4().hex
    a = k.add(dom, "ta", "ra", home=home)
    k.add(dom, "tb", "rb", home=home)
    k.bump_usage(a, home=home)
    k.bump_usage(a, home=home)  # a mer frekvent
    rows = k.top_k(dom, k=5, home=home)
    first = rows[0][0] if rows else None
    ok = first == "ta"
    return EvalResult("knowledge_lfu_topk", ok, f"first={first}")


def _proposal_core_change_forced() -> EvalResult:
    from hund_cli.selfimprovement import proposal as P

    p1 = P.build_from_gaps([], {"change_type": "core"})
    p2 = P.build_from_gaps([], {"change_type": "engine"})
    ok = p1.change_type == "runtime_policy" and p2.change_type == "runtime_policy"
    return EvalResult("proposal_core_change_forced", ok, f"{p1.change_type}/{p2.change_type}")


def _installer_sha_todo() -> EvalResult:
    root = Path(__file__).resolve().parents[3]  # hund_cli/evals/cases -> repo
    found = False
    for s in ("install.ps1", "install.sh"):
        f = root / s
        if f.exists() and "sha" in f.read_text(encoding="utf-8", errors="ignore").lower():
            found = True
    return EvalResult("installer_sha_todo", found, "SHA marker present" if found else "no SHA marker")


def _cli_help_imports_without_key() -> EvalResult:
    try:
        import hund_cli.main as m

        ok = m.app is not None
    except Exception as e:  # noqa: BLE001
        return EvalResult("cli_help_imports_without_key", False, f"EXC: {e}")
    return EvalResult("cli_help_imports_without_key", ok, "app imported")


BUILTIN_CASES = [
    _permission_write_outside_workspace,
    _tcb_tools_blocked,
    _prompt_tool_output_untrusted,
    _redactor_known_api_key,
    _provider_no_key_fails_clean,
    _doctor_no_git_rule,
    _knowledge_lfu_topk,
    _proposal_core_change_forced,
    _installer_sha_todo,
    _cli_help_imports_without_key,
]
