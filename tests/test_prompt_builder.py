"""Bevisar differentiatorn: miljöprofilen ÄNDRAR systemprompten (inte dekoration)."""
from __future__ import annotations

from hund_cli.agent.prompt_builder import build_system_prompt
from hund_cli.doctor import EnvironmentProfile


def _prof(**kw) -> EnvironmentProfile:
    base = dict(os="Windows", cpu_count=8, has_git=True, has_python=True,
                has_node=True, shell="pwsh",
                capabilities={"has_git": True, "can_run_python": True})
    base.update(kw)
    return EnvironmentProfile(**base)


def test_missing_git_adds_repo_block_rule():
    prof = _prof(has_git=False, capabilities={"has_git": False})
    prompt = build_system_prompt("P", prof)
    assert "git saknas" in prompt.lower()
    assert "blockera repo" in prompt.lower()


def test_weak_cpu_adds_compact_rule():
    prof = _prof(cpu_count=2)
    assert "begränsad cpu" in build_system_prompt("P", prof).lower()


def test_strong_machine_no_throttle():
    prof = _prof(cpu_count=16)
    assert "begränsad cpu" not in build_system_prompt("P", prof).lower()


def test_prompt_marks_tool_output_as_untrusted_data():
    prompt = build_system_prompt("P", _prof())
    low = prompt.lower()
    assert "tool-output" in low
    assert "obetrodd data" in low
    assert "inte instruktioner" in low


def test_policy_rules_injected_into_prompt():
    prompt = build_system_prompt(
        "P", _prof(), policy_rules=["regel A", "regel B"]
    )
    assert "policy (deklarativ" in prompt.lower()
    assert "regel A" in prompt
    assert "regel B" in prompt


def test_no_policy_section_when_rules_absent():
    prompt = build_system_prompt("P", _prof())
    assert "## Policy" not in prompt
