"""Tests for on-demand skill authoring intent detection, local inspection, research decisions, scope resolution, and pure factory."""
from pathlib import Path
import pytest

from hund.skills.authoring import (
    AuthoringAdvisory,
    CreateSkillToolArgs,
    LocalInspectionSnapshot,
    LocalSkillProposal,
    PublicationReceipt,
    ResearchDecision,
    ResearchSkillProposal,
    ResearchSourceRef,
    SkillAuthoringIntent,
    decide_research_need,
    detect_explicit_skill_intent,
    inspect_local_context,
    render_publication_receipt,
)
from hund.skills.factory import SkillFactory
from hund.skills.loader import load_builtins
from hund.skills.model import Skill
from hund.skills.scope import ScopeResolution, compute_workspace_key, resolve_scope_and_overlap


def test_intent_detection_en_sv():
    # English creation
    intent_en = detect_explicit_skill_intent("create a skill for markdown formatting")
    assert intent_en is not None
    assert intent_en.operation == "create"
    assert "markdown formatting" in intent_en.capability.lower()
    assert intent_en.confidence >= 0.9

    # Swedish creation
    intent_sv = detect_explicit_skill_intent("skapa en skill för markdown-formatering")
    assert intent_sv is not None
    assert intent_sv.operation == "create"
    assert "markdown-formatering" in intent_sv.capability.lower()

    # English update
    update_en = detect_explicit_skill_intent("update skill markdown-formatting with table support")
    assert update_en is not None
    assert update_en.operation == "update"
    assert update_en.referenced_name == "markdown-formatting"

    # Swedish update
    update_sv = detect_explicit_skill_intent("uppdatera skillen markdown-formatering med tabeller")
    assert update_sv is not None
    assert update_sv.operation == "update"
    assert update_sv.referenced_name == "markdown-formatering"

    # Disposition cues
    equip_intent = detect_explicit_skill_intent("create a skill for fast-grep and equip now")
    assert equip_intent is not None
    assert equip_intent.desired_disposition == "equip"

    vault_intent = detect_explicit_skill_intent("skapa en skill för git-commit och spara till valvet")
    assert vault_intent is not None
    assert vault_intent.desired_disposition == "vault"


def test_non_intent_filtering():
    non_intents = [
        "Vad är en skill?",
        "Hur fungerar skills i Hund?",
        "What is a skill?",
        "How do skills work?",
        "Kan du berätta om skills?",
        "Jag såg en skill om git",
        "I saw a skill called markdown",
        "Do you have skills?",
    ]
    for prompt in non_intents:
        assert detect_explicit_skill_intent(prompt) is None, f"Expected None for '{prompt}'"


def test_explicit_intent_bypasses_onboarding():
    intent = detect_explicit_skill_intent("skapa en ny skill för regex-validering")
    assert intent is not None
    assert intent.confidence >= 0.9
    assert intent.operation == "create"


def test_local_inspection_skips_research(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    intent = detect_explicit_skill_intent("create a skill for local file linting")
    assert intent is not None
    snapshot = inspect_local_context(tmp_path, {"read_file", "write_file"}, [])
    assert "pyproject.toml" in snapshot.config_files_found

    decision = decide_research_need(intent, snapshot)
    assert not decision.needs_research
    assert "sufficient" in decision.reason.lower() or "local" in decision.reason.lower()


def test_volatile_api_triggers_bounded_research(tmp_path: Path):
    intent = detect_explicit_skill_intent("create a skill for OpenAI API v3 integration")
    assert intent is not None
    snapshot = inspect_local_context(tmp_path, {"read_file"}, [])

    decision = decide_research_need(intent, snapshot)
    assert decision.needs_research
    assert len(decision.search_queries) > 0
    assert "openai" in decision.search_queries[0].lower()


def test_local_only_suppresses_research(tmp_path: Path):
    intent = detect_explicit_skill_intent("create a skill for Stripe API v3 offline utan webbsökning")
    assert intent is not None
    assert intent.local_only
    snapshot = inspect_local_context(tmp_path, {"read_file"}, [])

    decision = decide_research_need(intent, snapshot)
    assert not decision.needs_research
    assert "local-only" in decision.reason.lower()


def test_private_queries_sanitized_in_research(tmp_path: Path):
    intent = detect_explicit_skill_intent("create a skill for C:/Users/William/secret/repo AWS Cloud API")
    assert intent is not None
    snapshot = inspect_local_context(tmp_path, set(), [])

    decision = decide_research_need(intent, snapshot)
    if decision.needs_research:
        for q in decision.search_queries:
            assert "c:/" not in q.lower()
            assert "william" not in q.lower()
            assert "secret" not in q.lower()


def test_exact_lineage_update_resolution():
    existing = Skill(
        schema_version=1,
        name="test-skill",
        domain="general",
        status="active",
        triggers=("test trigger",),
        when_to_use="When testing.",
        steps=("Step 1",),
        required_tools=(),
        forbidden_actions=("modify_tcb", "self_update", "apply_update", "elevate_permissions"),
        safety_level="read_only",
        verification=("Verify it.",),
        version="1.0.0",
        capability_id="general/test-skill",
        scope="global",
    )
    intent = detect_explicit_skill_intent("update skill test-skill to add step 2")
    assert intent is not None

    resolution = resolve_scope_and_overlap(intent, "global", [existing], [])
    assert resolution.status == "RESOLVED"
    assert resolution.action == "UPDATE"
    assert resolution.existing_skill == existing
    assert resolution.target_name == "test-skill"


def test_strong_overlap_deduplication():
    global_skill = Skill(
        schema_version=1,
        name="formatter",
        domain="general",
        status="active",
        triggers=("format code",),
        when_to_use="When formatting.",
        steps=("Step 1",),
        required_tools=(),
        forbidden_actions=("modify_tcb", "self_update", "apply_update", "elevate_permissions"),
        safety_level="read_only",
        verification=("Verify it.",),
        version="1.0.0",
        capability_id="general/formatter",
        scope="global",
    )
    intent = detect_explicit_skill_intent("create a skill for formatter for this project")
    assert intent is not None
    assert intent.target_scope == "project"

    resolution = resolve_scope_and_overlap(intent, "ws1234567890abcd", [global_skill], [])
    assert resolution.status == "RESOLVED"
    assert resolution.target_scope == "project"
    assert resolution.is_shadowing is True


def test_ambiguous_scope_prompts_clarification():
    intent = SkillAuthoringIntent(
        operation="create",
        capability="project special tool",
        target_scope="unresolved",
        referenced_name=None,
        local_only=False,
        requires_research=False,
        confidence=0.9,
        raw_prompt="create a project skill for special tool",
    )
    resolution = resolve_scope_and_overlap(intent, "global", [], [])
    assert resolution.status == "CLARIFICATION_REQUIRED"
    assert "scope" in resolution.reason.lower()


def test_same_name_cross_project_isolation(tmp_path: Path):
    ws_a = tmp_path / "project_a"
    ws_b = tmp_path / "project_b"
    ws_a.mkdir()
    ws_b.mkdir()

    key_a = compute_workspace_key(ws_a)
    key_b = compute_workspace_key(ws_b)
    assert len(key_a) == 16
    assert len(key_b) == 16
    assert key_a != key_b


def test_builtin_collision_rejected():
    builtins = load_builtins()
    builtin_name = builtins[0].name if builtins else "file-operations"

    intent = detect_explicit_skill_intent(f"create a skill for {builtin_name}")
    assert intent is not None

    resolution = resolve_scope_and_overlap(intent, "global", [], builtins)
    assert resolution.status == "REJECTED"
    assert "constitutional builtin" in resolution.reason


def test_workspace_key_sanitization_no_path_leak(tmp_path: Path):
    path = tmp_path / "my sensitive folder (secret)"
    path.mkdir()
    key = compute_workspace_key(path)
    assert "\\" not in key
    assert "/" not in key
    assert "sensitive" not in key
    assert "secret" not in key
    assert len(key) == 16


def test_pure_skill_factory_build():
    factory = SkillFactory()
    proposal = LocalSkillProposal(
        name="markdown-helper",
        domain="general",
        intent="markdown helper",
        scope="global",
        steps=("Format headers with #", "Format tables with |"),
        required_tools=(),
        when_to_use="When formatting markdown files.",
        triggers=("format markdown", "markdown helper"),
        verification=("Check markdown syntax.",),
        examples=("Du> format markdown",),
    )
    resolution = ScopeResolution(
        status="RESOLVED",
        action="CREATE",
        target_scope="global",
        workspace_key="global",
        capability_id="general/markdown-helper",
        target_name="markdown-helper",
    )

    draft = factory.build_from_proposal(proposal, resolution)
    assert draft.action == "CREATE"
    assert draft.skill.name == "markdown-helper"
    assert draft.skill.version == "1.0.0"
    assert draft.skill.personal_skill_xp == 0
    assert draft.skill.lifecycle_state == "draft"
    assert draft.skill.vault_state == "vaulted"
    assert draft.skill.safety_level == "read_only"

    # Test update bump
    existing = draft.skill
    update_res = ScopeResolution(
        status="RESOLVED",
        action="UPDATE",
        target_scope="global",
        workspace_key="global",
        capability_id="general/markdown-helper",
        target_name="markdown-helper",
        existing_skill=existing,
    )
    draft_v2 = factory.build_from_proposal(proposal, update_res, [existing])
    assert draft_v2.action == "UPDATE"
    assert draft_v2.skill.version == "1.1.0"
    assert draft_v2.skill.personal_skill_xp == 0


def test_authoring_advisory_variants():
    adv_none = AuthoringAdvisory(status="NONE")
    assert adv_none.status == "NONE"

    adv_clarify = AuthoringAdvisory(status="CLARIFICATION_REQUIRED", message="Please clarify scope.")
    assert adv_clarify.status == "CLARIFICATION_REQUIRED"

    adv_reject = AuthoringAdvisory(status="REJECTED", message="Cannot overwrite builtin.")
    assert adv_reject.status == "REJECTED"

    args = CreateSkillToolArgs(request="create a skill for x", target_scope="global", desired_disposition="auto")
    adv_call = AuthoringAdvisory(status="CALL_CREATE_SKILL", message="Call create_skill", tool_args=args)
    assert adv_call.status == "CALL_CREATE_SKILL"
    assert adv_call.tool_args is not None
    assert adv_call.tool_args.request == "create a skill for x"


def test_f1_swedish_and_english_connectors():
    cases = [
        ("skapa en skill om marketing", "marketing"),
        ("skapa en skill kring B2B outreach", "B2B outreach"),
        ("skapa en skill gällande kundsupport", "kundsupport"),
        ("skapa en skill angående release reviews", "release reviews"),
        ("skapa en skill avseende säkerhetsanalys", "säkerhetsanalys"),
        ("skapa en skill rörande logghantering", "logghantering"),
        ("create a skill for marketing strategy", "marketing strategy"),
        ("create a skill about customer onboarding", "customer onboarding"),
        ("create a skill regarding release notes", "release notes"),
    ]
    for prompt, expected_cap in cases:
        intent = detect_explicit_skill_intent(prompt)
        assert intent is not None, f"Failed to detect intent for: {prompt}"
        assert intent.operation == "create"
        assert intent.capability.lower() == expected_cap.lower(), (
            f"Expected capability '{expected_cap}', got '{intent.capability}' for '{prompt}'"
        )


def test_f1_om_never_extracted_as_capability():
    intent = detect_explicit_skill_intent("skapa en skill om marketing")
    assert intent is not None
    assert intent.capability.lower() != "om"
    assert not intent.capability.lower().startswith("om ")

    # Bare connector without payload must not produce a valid skill capability
    bare_intent = detect_explicit_skill_intent("skapa en skill om")
    assert bare_intent is None or bare_intent.capability.lower() != "om"


def test_f1_negative_and_question_forms_rejected():
    neg_and_questions = [
        "ska inte skapa en skill om marketing",
        "skapa inte en skill om marketing",
        "vill inte skapa en skill om marketing",
        "don't create a skill for marketing",
        "do not create a skill for marketing",
        "ska vi skapa en skill om marketing?",
        "should I create a skill for marketing?",
        "borde jag skapa en skill om marketing?",
        "hur skapar jag en skill om marketing?",
        "why should I create a skill for marketing?",
    ]
    for prompt in neg_and_questions:
        intent = detect_explicit_skill_intent(prompt)
        assert intent is None, f"Expected None for negative/question prompt: '{prompt}', got {intent}"


@pytest.mark.parametrize(
    ("prompt", "expected_capability"),
    [
        (
            "Kan du bygga en skill om git-rebase och squashing?",
            "git-rebase och squashing",
        ),
        (
            "Skulle du kunna skapa en skill om dependency review?",
            "dependency review",
        ),
        (
            "Could you build me a skill about PostgreSQL query review?",
            "PostgreSQL query review",
        ),
        ("Can you make a skill for release notes?", "release notes"),
    ],
)
def test_polite_skill_authoring_questions_are_explicit_commands(
    prompt: str, expected_capability: str
):
    intent = detect_explicit_skill_intent(prompt)

    assert intent is not None
    assert intent.operation == "create"
    assert intent.capability == expected_capability


@pytest.mark.parametrize(
    ("prompt", "expected_capability"),
    [
        ("Gör en skill kring B2B outreach åt mig.", "B2B outreach"),
        ("Skapa en skill om incidenttriage för mig.", "incidenttriage"),
        ("Bygg en skill kring release review till mig.", "release review"),
        ("Create a skill about B2B outreach for me.", "B2B outreach"),
    ],
)
def test_conversational_suffixes_do_not_pollute_capability(
    prompt: str, expected_capability: str
):
    intent = detect_explicit_skill_intent(prompt)

    assert intent is not None
    assert intent.capability == expected_capability


def test_f1_plural_and_batch_preserved():
    intent = detect_explicit_skill_intent("skapa en skill om marketing och sales")
    assert intent is not None
    assert "marketing och sales" in intent.capability.lower()

    intent_en = detect_explicit_skill_intent("create a skill for frontend and backend")
    assert intent_en is not None
    assert "frontend and backend" in intent_en.capability.lower()


def test_f1_typo_and_punctuation_resilience():
    cases = [
        ("skapa en skill: marketing", "marketing"),
        ("skapa en skill om 'marketing'", "marketing"),
        ("skapa skill om marketing.", "marketing"),
    ]
    for prompt, expected_cap in cases:
        intent = detect_explicit_skill_intent(prompt)
        assert intent is not None, f"Failed for: {prompt}"
        assert intent.capability.lower() == expected_cap.lower()
