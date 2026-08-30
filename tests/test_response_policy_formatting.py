"""Tests for response policy rules and advisory directives."""
from __future__ import annotations

import pytest

from hund.agent.prompt_builder import build_system_prompt
from hund.agent.response_policy import (
    get_response_policy_rules,
    render_advisory_directives,
)
from hund.agent.task_brief import ResponseFormat, TaskBrief, TaskType
from hund.doctor import EnvironmentProfile


def test_get_response_policy_rules_swedish_and_english() -> None:
    """Verify response policy rules in both languages."""
    rules_sv = get_response_policy_rules(language="sv")
    assert len(rules_sv) >= 8
    assert any("så kort som möjligt och så komplett som nödvändigt" in r.lower() for r in rules_sv)
    assert any("avsluta inte identitets-" in r.lower() for r in rules_sv)
    assert any("punktlistor endast när innehållet faktiskt består av minst tre" in r for r in rules_sv)
    assert any("introducera koden kort med 1 mening" in r for r in rules_sv)
    assert any("renderas koden och diffen automatiskt i aktivitetsfeeden" in r for r in rules_sv)
    assert any("Deklarera osäkerhet ärligt" in r for r in rules_sv)
    assert any("är det en spec att agera på och genomföra" in r for r in rules_sv)

    rules_en = get_response_policy_rules(language="en")
    assert len(rules_en) >= 8
    assert any("as short as possible and as complete as necessary" in r.lower() for r in rules_en)
    assert any("do not ask the user for a task" in r.lower() for r in rules_en)
    assert any("introduce the snippet with 1 sentence" in r for r in rules_en)
    assert any("treat it as a specification to execute immediately" in r for r in rules_en)


def test_render_advisory_directives() -> None:
    """Verify turn-local advisory directives formatting."""
    # Prose brief
    brief_prose = TaskBrief(
        task_type=TaskType.DIRECT_ANSWER,
        requested_outcome="Answer",
        confidence=0.9,
        scope="general",
        preferred_format=ResponseFormat.PROSE,
    )
    res_prose = render_advisory_directives(brief_prose, language="sv")
    assert "Formatera som naturlig prosa med längd efter uppgiftens komplexitet." in res_prose

    # Recommendation brief
    brief_rec = TaskBrief(
        task_type=TaskType.RECOMMENDATION,
        requested_outcome="Model advice",
        confidence=0.9,
        scope="system",
        preferred_format=ResponseFormat.LIST,
        requires_disk_vram_separation=True,
        requires_uncertainty_disclosure=True,
    )
    res_rec = render_advisory_directives(brief_rec, language="sv")
    assert "Presentera som en kort, fokuserad lista." in res_rec
    assert "Separera tydligt system-RAM, GPU-VRAM och diskutrymme" in res_rec
    assert "Märk uppskattningar och overifierade antaganden tydligt." in res_rec


def test_prompt_builder_consumes_response_policy_rules() -> None:
    """Verify build_system_prompt incorporates canonical response policy rules."""
    profile = EnvironmentProfile(
        os="Windows",
        os_version="11.0",
        os_caption="Windows 11 Pro",
        os_arch="64-bit",
        hostname="TEST-PC",
        processor="Test CPU",
        cpu_count=8,
        gpu_model="Test GPU",
        gpu_vram_mb=4096,
        total_ram_gb=16.0,
        shell="powershell",
        capabilities={"git": True, "python": True, "node": False, "docker": False, "wsl": False},
    )
    prompt = build_system_prompt("Hund test persona.", profile)
    assert "## Output-formatering och visuell hierarki i terminalen" in prompt
    assert "As short as possible and as complete as necessary." in prompt
    assert "Do not ask the user for a task" in prompt
    assert "1-4 lines" not in prompt
    assert "introduce the snippet with 1 sentence" in prompt
    # Invariant: system prompt canonical rules are English, not hardcoded Swedish
    assert "så kort som möjligt" not in prompt.lower()
