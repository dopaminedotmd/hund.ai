"""Tests for Phase 4: Persona, Self-Knowledge, and Prompt Efficiency."""
import hashlib
from pathlib import Path
import pytest

from hund.agent.capability_self_model import (
    CapabilityDescriptor,
    find_matching_capabilities,
    get_capability_descriptor,
)
from hund.agent.loop import assemble_system_prompt
from hund.agent.narrative_validation import (
    repair_narrative_prose,
    validate_and_repair_response,
    validate_narrative_text,
)
from hund.agent.prompt_budget import PromptBudgetReport, compute_prompt_hash, estimate_tokens
from hund.agent.prompt_builder import build_system_prompt
from hund.agent.task_brief import TaskBrief, TaskType
from hund.agent.task_policy import classify_task
from hund.agent.turn_context import TurnContext, compose_turn_context_message, resolve_typed_state
from hund.doctor import EnvironmentProfile
from hund.persona import (
    COMPACT_VOICE_CONTRACT,
    get_compact_voice_contract,
    load_canonical_persona,
    load_persona,
    load_runtime_persona,
)


def _profile() -> EnvironmentProfile:
    return EnvironmentProfile(
        os="Windows",
        os_version="11 Pro",
        os_arch="x86_64",
        os_caption="Windows 11 Pro (25H2)",
        hostname="Blade-Stealth",
        cpu_count=8,
        processor="Intel(R) Core(TM) i7-8550U",
        gpu_model="NVIDIA GeForce GTX 1080 Ti",
        gpu_vram_mb=11264,
        total_ram_gb=16.0,
        shell="pwsh",
        has_git=True,
        has_python=True,
        has_node=True,
        capabilities={"git": True, "python": True, "node": True, "docker": False, "ripgrep": True},
    )


def test_compact_voice_contract_budget():
    """Assert compact voice contract is <= 1,500 chars and >= 60% reduced from canonical persona."""
    canonical = load_canonical_persona()
    compact = get_compact_voice_contract()

    # 1. Budget constraint: <= 1,500 chars
    assert len(compact) <= 1500, f"Compact voice contract is {len(compact)} chars, exceeds 1,500 char budget"

    # 2. Reduction constraint: >= 60% reduction from baseline
    reduction = (len(canonical) - len(compact)) / len(canonical)
    assert reduction >= 0.60, f"Reduction was {reduction:.1%}, expected >= 60%"


def test_system_prompt_budget_reduction():
    """Assert total fixed system prompt is reduced >= 35% from baseline."""
    profile = _profile()
    canonical = load_canonical_persona()
    compact = get_compact_voice_contract()

    optimized_prompt = build_system_prompt(compact, profile)
    # Baseline prompt size without persona compression
    baseline_size = len(canonical) + len(optimized_prompt) - len(compact)

    reduction = (baseline_size - len(optimized_prompt)) / baseline_size
    assert reduction >= 0.35, f"System prompt reduction was {reduction:.1%}, expected >= 35%"
    assert len(optimized_prompt) <= 6500


def test_runtime_persona_uses_compact_contract():
    runtime_persona = load_runtime_persona()

    assert runtime_persona == get_compact_voice_contract()
    assert len(runtime_persona) <= 1500


def test_system_prompt_hash_stability():
    """Assert system prompt hash is stable across turns with identical environment/policy."""
    profile = _profile()
    persona = load_persona()

    prompt_turn1 = assemble_system_prompt(persona, profile)
    prompt_turn2 = assemble_system_prompt(persona, profile)
    prompt_turn3 = assemble_system_prompt(persona, profile)

    hash1 = compute_prompt_hash(prompt_turn1)
    hash2 = compute_prompt_hash(prompt_turn2)
    hash3 = compute_prompt_hash(prompt_turn3)

    assert hash1 == hash2 == hash3
    assert hash1.startswith("sha256:")


def test_direct_self_knowledge_routing_zero_tools():
    """Assert stable self-knowledge questions route to DIRECT_ANSWER / SELF_KNOWLEDGE with zero tools."""
    # Question: "Hur ser jag mina skills?"
    brief = classify_task("Hur ser jag mina skills?")
    assert brief.task_type == TaskType.SELF_KNOWLEDGE
    assert brief.needs_workspace_context is False
    assert brief.needs_environment_facts is False
    assert brief.needs_web_research is False
    assert brief.relevant_command == "skills"

    # Question: "Vad gör /history?"
    brief_hist = classify_task("Vad gör /history?")
    assert brief_hist.task_type == TaskType.SELF_KNOWLEDGE
    assert brief_hist.relevant_command == "history"


def test_typed_current_state_routing():
    """Assert current-state questions route to CURRENT_STATE and resolve from typed state."""
    brief = classify_task("Vilka skills är aktiva just nu?")
    assert brief.task_type == TaskType.CURRENT_STATE
    assert brief.needs_workspace_context is False
    assert brief.needs_environment_facts is False
    assert brief.needs_web_research is False

    # Test typed state resolution without tools
    state_str = resolve_typed_state("skills")
    assert "Current Active Skills" in state_str
    assert "Constitutional motor skills active" in state_str or "domain skills" in state_str


def test_narrative_validation_and_repair_invariants():
    """Assert narrative validation fixes Swedish first-person slips while preserving code."""
    raw_response = """Jag har undersökt problemet och jag föreslår följande lösning:

```python
def check_status(user_input: str) -> bool:
    # Jag testar detta med min flagga
    return "jag" in user_input
```

Jag rekommenderar att vi kör testet."""

    cleaned, res = validate_and_repair_response(raw_response, language="sv")

    # Invariants:
    # 1. First-person in narrative is repaired to third person
    assert "hund har undersökt problemet" in cleaned.lower()
    assert "hund föreslår" in cleaned.lower()
    assert "hund rekommenderar" in cleaned.lower()

    # 2. Code fence is preserved byte-for-byte
    assert '# Jag testar detta med min flagga' in cleaned
    assert 'return "jag" in user_input' in cleaned

    # 3. No emojis in narrative
    assert "🚀" not in cleaned


def test_narrative_fallback_on_unrepairable_violation():
    """Assert safe fallback is returned if repair cannot satisfy persona invariants."""
    raw_response = "Jag Jag Jag Jag Jag"
    # Even if repeated, repair handles it or fallback triggers
    cleaned, res = validate_and_repair_response(raw_response, language="sv")
    assert "jag" not in cleaned.lower()
    assert "hund" in cleaned.lower()
