"""Loop-integration — deklarativa lager (policy + skills) når systemprompten."""
from __future__ import annotations

from hund_cli.agent.loop import assemble_system_prompt
from hund_cli.doctor import EnvironmentProfile


def _prof() -> EnvironmentProfile:
    return EnvironmentProfile(
        os="Windows",
        cpu_count=8,
        has_git=True,
        has_python=True,
        has_node=True,
        shell="pwsh",
        capabilities={"has_git": True, "can_run_python": True},
    )


def _skill(name="python-project-inspection", triggers=("pytest",)):
    from hund_cli.skills.model import Skill

    return Skill(
        schema_version=1,
        name=name,
        domain="software-development",
        status="active",
        triggers=triggers,
        when_to_use="när X",
        steps=("steg",),
        required_tools=("read_file",),
        forbidden_actions=("delete", "self_update"),
        safety_level="confirm_for_write",
        verification=("uv run pytest",),
    )


def test_policy_rules_reach_prompt():
    prompt = assemble_system_prompt(
        "P", _prof(), policy_rules=["REGEL-X"], skills=[], user_text="hej"
    )
    assert "REGEL-X" in prompt
    assert "## Policy" in prompt


def test_matched_skills_reach_prompt():
    prompt = assemble_system_prompt(
        "P", _prof(), skills=[_skill()], user_text="kör pytest åt mig"
    )
    assert "python-project-inspection" in prompt
    assert "## Relevanta skills" in prompt


def test_no_skill_section_without_user_text():
    prompt = assemble_system_prompt(
        "P", _prof(), skills=[_skill()], user_text=""
    )
    assert "## Relevanta skills" not in prompt


def test_unmatched_skill_not_injected():
    prompt = assemble_system_prompt(
        "P", _prof(), skills=[_skill(triggers=("rust",))], user_text="kör pytest"
    )
    assert "## Relevanta skills" not in prompt
