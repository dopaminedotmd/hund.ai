"""Tests for typed capability self-model adapter over CommandSpec."""
from hund.agent.capability_self_model import (
    CapabilityDescriptor,
    find_matching_capabilities,
    get_all_capabilities,
    get_capability_descriptor,
    render_capability_context,
)
from hund.ui.command_spec import COMMAND_REGISTRY


def test_capability_descriptors_match_command_registry():
    all_caps = get_all_capabilities()
    assert len(all_caps) > 0

    # Ensure every non-hidden command in COMMAND_REGISTRY has a corresponding descriptor
    non_hidden_specs = [s for s in COMMAND_REGISTRY if not s.is_hidden]
    assert len(all_caps) == len(non_hidden_specs)

    # Check /skills descriptor
    skills_cap = get_capability_descriptor("skills")
    assert skills_cap is not None
    assert skills_cap.id == "skills"
    assert "/skills" in skills_cap.relevant_commands
    assert skills_cap.inspection_boundary == "typed_state"
    assert "vault" in skills_cap.synonyms_and_intents


def test_intent_matching_swedish_and_english():
    # Swedish query about skills
    matches_sv = find_matching_capabilities("Hur ser jag mina skills och förmågor?")
    assert len(matches_sv) > 0
    assert matches_sv[0].id == "skills"

    # English query about history
    matches_en = find_matching_capabilities("Can I search previous turn history?")
    assert len(matches_en) > 0
    assert matches_en[0].id == "history"

    # Doctor query
    matches_doc = find_matching_capabilities("Kör en hälsokontroll och diagnosticera systemet")
    assert len(matches_doc) > 0
    assert matches_doc[0].id == "doctor"
    assert matches_doc[0].inspection_boundary == "inspection"


def test_render_capability_context_compact():
    skills_cap = get_capability_descriptor("skills")
    assert skills_cap is not None
    rendered = render_capability_context([skills_cap])
    assert "## Hund Capabilities" in rendered
    assert "Skills" in rendered
    assert "/skills" in rendered
    # Must be compact (<= 500 characters for 1 descriptor)
    assert len(rendered) <= 500
