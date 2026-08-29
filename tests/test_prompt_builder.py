"""Bevisar differentiatorn: miljöprofilen ÄNDRAR systemprompten (inte dekoration)."""
from __future__ import annotations

from hund.agent.prompt_builder import build_system_prompt
from hund.doctor import EnvironmentProfile


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


def test_persona_truncation():
    """Om persona överstiger 10KB, ska den trunkeras till början + slutet."""
    huge_persona = "A" * 7000 + "B" * 5000  # 12KB totalt
    prof = _prof()
    prompt = build_system_prompt(huge_persona, prof)

    assert "[TRUNCATD: 12000 chars totalt" in prompt
    assert prompt.startswith("A" * 6000)
    # prompt slutar på tail-delen (2000 tecken) samt resten av systemprompten, så vi kollar om "B"*2000 finns i den
    assert "B" * 2000 in prompt
    # Kontrollera att det inte finns fler A och B än vad som är tillåtet
    assert "A" * 6001 not in prompt


def test_project_context_truncation():
    """Om project_context överstiger 10KB, ska den trunkeras."""
    huge_context = "C" * 7000 + "D" * 5000  # 12KB totalt
    prof = _prof()
    prompt = build_system_prompt("P", prof, project_context=huge_context)

    assert "[TRUNCATD: 12000 chars totalt" in prompt
    assert "C" * 6000 in prompt
    assert "D" * 2000 in prompt


def test_web_rules_injected_into_prompt():
    prompt = build_system_prompt("P", _prof())
    low = prompt.lower()
    assert "## web tools" in low
    assert "pythagoras" in low
    assert "aktuella positioner" in low
    assert "5-10 for research" in low


def test_output_formatting_is_adaptive_not_bullet_default():
    prompt = build_system_prompt("P", _prof())
    low = prompt.lower()
    assert "the standard response format is natural, concise prose" in low
    assert "use bullet lists only when" in low
    assert "formatting is an ability, not a house style" in low
    assert "plain prose first" in low
    assert "bold is for semantic emphasis" in low
    assert "avoid bold label prefixes" in low
    assert "använd punktlistor med tydliga fetstilta rubriker" not in low
    assert "standardformatet är naturlig, kompakt prosa" not in low
