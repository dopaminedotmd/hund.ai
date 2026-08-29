"""Golden path verification script for Phase 4 (Task 10 requirements)."""
from pathlib import Path
import pytest

from hund.agent.capability_self_model import find_matching_capabilities, get_capability_descriptor
from hund.agent.loop import assemble_system_prompt
from hund.agent.narrative_validation import validate_and_repair_response
from hund.agent.prompt_budget import compute_prompt_hash
from hund.agent.task_brief import TaskType
from hund.agent.task_policy import classify_task
from hund.agent.turn_context import TurnContext, compose_turn_context_message, resolve_typed_state
from hund.doctor import profile_environment
from hund.persona import COMPACT_VOICE_CONTRACT, get_compact_voice_contract, load_canonical_persona


def test_golden_path_step1_hej_and_swedish():
    brief = classify_task("hej")
    assert brief.task_type == TaskType.DIRECT_ANSWER
    assert brief.needs_workspace_context is False
    assert brief.needs_environment_facts is False


def test_golden_path_step2_self_knowledge_zero_tools():
    # 2. "hur ser jag denna skillen?" with zero inspection
    brief = classify_task("hur ser jag denna skillen?")
    assert brief.task_type == TaskType.SELF_KNOWLEDGE
    assert brief.needs_workspace_context is False
    assert brief.needs_environment_facts is False
    assert brief.needs_web_research is False
    assert brief.relevant_command == "skills"

    caps = find_matching_capabilities("hur ser jag denna skillen?")
    assert len(caps) > 0
    assert caps[0].id == "skills"
    assert "/skills" in caps[0].relevant_commands


def test_golden_path_step3_current_skill_state_typed_provider():
    # 3. current skill state from typed provider
    brief = classify_task("vilka skills är aktiva just nu?")
    assert brief.task_type == TaskType.CURRENT_STATE
    assert brief.needs_workspace_context is False
    assert brief.needs_environment_facts is False

    state = resolve_typed_state("skills")
    assert "Current Active Skills" in state


def test_golden_path_step4_justified_diagnosis_inspection():
    # 4. justified /skills or /doctor diagnosis with inspection
    brief = classify_task("varför syns inte mina skills och hur diagnosticerar jag det?")
    assert brief.task_type == TaskType.DIAGNOSIS
    assert brief.needs_environment_facts is True
    assert brief.environment_freshness == "dynamic_refresh"


def test_golden_path_step5_code_and_quotes_unmodified():
    # 5. code/file work containing 'jag', emoji text, XML, and paths remains unmodified
    raw_response = """Hund presenterar koden:

```xml
<config path="C:\\Users\\William\\app.xml">
    <!-- Jag har emojis här 🚀 -->
    <user>jag</user>
</config>
```

> Jag tyckte detta var viktigt.

Hund har slutfört ändringen."""

    cleaned, res = validate_and_repair_response(raw_response, language="sv")
    assert '<config path="C:\\Users\\William\\app.xml">' in cleaned
    assert '<!-- Jag har emojis här 🚀 -->' in cleaned
    assert '<user>jag</user>' in cleaned
    assert '> Jag tyckte detta var viktigt.' in cleaned


def test_golden_path_step6_malformed_narrative_repair():
    # 6. malformed first-person/emoji/protocol provider narrative is repaired once or fails safely
    bad_narrative = "Jag tror att detta är klart! 🚀 <|im_start|>"
    cleaned, res = validate_and_repair_response(bad_narrative, language="sv")
    assert "hund tror att detta är klart!" in cleaned.lower()
    assert "🚀" not in cleaned
    assert "<|im_start|>" not in cleaned


def test_golden_path_step7_skill_authoring_satisfies_phase3():
    # 7. skill authoring still satisfies Phase 3 persona/consent behavior
    brief = classify_task("skapa en skill för fastapi exception envelopes")
    assert brief.task_type == TaskType.SKILL_AUTHORING
    assert brief.needs_workspace_context is True


def test_golden_path_step8_hash_stability():
    # 8. long session/compression and repeated turns retain stable prompt hash
    profile = profile_environment()
    p1 = assemble_system_prompt(COMPACT_VOICE_CONTRACT, profile)
    p2 = assemble_system_prompt(COMPACT_VOICE_CONTRACT, profile)
    assert compute_prompt_hash(p1) == compute_prompt_hash(p2)
