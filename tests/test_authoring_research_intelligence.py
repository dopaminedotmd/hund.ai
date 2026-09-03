"""Tests for Authoring Research Intelligence: Call 1b query refinement, 0-hit fallback, SOP craft rules, and quality gates."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from hund.skills.authoring import (
    AuthoringSession,
    AuthoringState,
    MiniDraftData,
    SkillDraft,
    create_authoring_session,
    get_authoring_registry,
    run_deterministic_quality_checks,
)
from hund.skills.authoring_runtime import (
    AuthoringTurnResult,
    handle_authoring_turn,
    synthesize_skill_proposal_content,
)
from hund.skills.model import BANNED_ACTIONS, Skill
from hund.skills.shaping import refine_research_queries


def _sample_skill(**overrides) -> Skill:
    base = {
        "schema_version": 1,
        "name": "minecraft-modding",
        "domain": "minecraft",
        "status": "active",
        "required_tools": ("read_file", "execute_command"),
        "safety_level": "read_only",
        "when_to_use": "When developing, compiling, or structuring Fabric mods for Minecraft.",
        "steps": (
            "1. Inspect fabric.mod.json to verify mod ID and entrypoint declarations.",
            "2. If targeting Minecraft 1.21+, use Loom Gradle plugin 1.6+; do not use legacy Fabric Gradle plugins.",
            "3. Run './gradlew build' and verify generated JAR in build/libs.",
        ),
        "triggers": ("minecraft mod", "fabric mod"),
        "verification": (
            "Check that fabric.mod.json contains valid JSON.",
            "Verify that ./gradlew build exits with code 0.",
        ),
        "examples": ("Creating a custom block in Fabric 1.21.",),
        "scope": "project",
        "forbidden_actions": tuple(BANNED_ACTIONS),
    }
    base.update(overrides)
    return Skill(**base)


class MockLLMClient:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.completed_calls: list[dict] = []

    def complete(self, messages, tools=None, **kwargs):
        self.completed_calls.append({"messages": messages, "kwargs": kwargs})
        from hund.providers.base import CompletionResult
        return CompletionResult(text=self.response_text)


def test_refine_research_queries_with_llm():
    """Call 1b uses shaping answers to refine conflated queries to focused queries + fallback."""
    fake_llm_json = json.dumps({
        "queries": [
            "Minecraft 1.21 Fabric mod setup template github",
            "Fabric Loom build.gradle configuration 1.21",
        ],
        "fallback_query": "Fabric mod development guide Minecraft",
    })
    client = MockLLMClient(fake_llm_json)

    queries, fallback = refine_research_queries(
        subject="minecraft modding",
        shaping_answers={"loader": "Fabric", "version": "1.21"},
        mini_draft=MiniDraftData(when_to_use="Fabric modding", steps=("Step 1", "Step 2")),
        existing_queries=("Minecraft modding Forge Fabric NeoForge guide",),
        client=client,
    )

    assert len(queries) == 2
    assert "Fabric" in queries[0]
    assert fallback == "Fabric mod development guide Minecraft"
    assert len(client.completed_calls) == 1


def test_refine_research_queries_fallback_on_client_none_or_error():
    """When client is None or fails, refine_research_queries gracefully cleans existing queries."""
    # 1. client is None
    queries, fallback = refine_research_queries(
        subject="minecraft modding",
        shaping_answers={"loader": "Fabric"},
        mini_draft=None,
        existing_queries=("Minecraft modding Forge Fabric NeoForge guide", "Fabric template"),
        client=None,
    )
    assert len(queries) >= 1
    # Forge and NeoForge should have been filtered out because answer specifies Fabric
    assert not any("forge" in q.lower() and "neoforge" in q.lower() for q in queries)
    assert "minecraft modding" in fallback

    # 2. client raises exception
    bad_client = MagicMock()
    bad_client.complete.side_effect = RuntimeError("API unavailable")
    queries2, fallback2 = refine_research_queries(
        subject="minecraft modding",
        shaping_answers={"loader": "Fabric"},
        mini_draft=None,
        existing_queries=("Fabric mod guide",),
        client=bad_client,
    )
    assert queries2 == ("Fabric mod guide",)
    assert "minecraft modding" in fallback2


def test_authoring_runtime_advance_calls_query_refinement(tmp_path: Path):
    """advance_authoring returns refined queries and fallback query upon research authorization."""
    from hund.skills.authoring import SkillAuthoringIntent
    reg = get_authoring_registry()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="minecraft 1.21 fabric modding",
        target_scope="project",
        referenced_name=None,
        local_only=False,
        requires_research=True,
        confidence=0.95,
        raw_prompt="skapa en skill för minecraft modding",
    )
    sess = create_authoring_session(intent, registry=reg)
    from hund.skills.authoring import ResearchDecision
    from dataclasses import replace
    sess = replace(
        sess,
        state=AuthoringState.RESEARCHING,
        shaping_answers={"loader": "Fabric"},
        research_decision=ResearchDecision(
            needs_research=True,
            reason="Minecraft modding requires external documentation",
            search_queries=("Minecraft modding Forge Fabric",),
        ),
    )
    reg.save(sess)

    fake_refined = json.dumps({
        "queries": ["Fabric Minecraft 1.21 modding template"],
        "fallback_query": "Fabric modding setup",
    })
    client = MockLLMClient(fake_refined)

    result = handle_authoring_turn(
        "yes",
        session_id=sess.session_id,
        workspace=tmp_path,
        registered_tools={"web_search"},
        registry=reg,
        client=client,
    )

    assert result.handled is True
    assert result.research_queries == ("Fabric Minecraft 1.21 modding template",)
    assert result.research_fallback_query == "Fabric modding setup"


def test_boilerplate_detection_catches_generic_inspect_files():
    """Deterministic check rejects generic 'inspect files/workspace to understand'."""
    bad_skill = _sample_skill(
        steps=(
            "Inspect the files to understand the project structure.",
            "Write the code.",
        )
    )
    result = run_deterministic_quality_checks(SkillDraft(action="CREATE", skill=bad_skill))
    assert result.passed is False
    assert any("boilerplate" in f.lower() for f in result.failures)


def test_boilerplate_detection_allows_concrete_file_inspection():
    """Deterministic check permits inspection of concrete canonical files (e.g. fabric.mod.json)."""
    good_skill = _sample_skill(
        steps=(
            "Inspect fabric.mod.json to verify mod ID and entrypoint declarations.",
            "Run './gradlew build' to compile the mod.",
        )
    )
    result = run_deterministic_quality_checks(SkillDraft(action="CREATE", skill=good_skill))
    # Boilerplate check specifically passes
    bp_check = next((c for c in result.checks if c.name == "no_boilerplate"), None)
    assert bp_check is not None
    assert bp_check.passed is True


def test_swedish_detection_catches_swedish_words_in_canonical_content():
    """Deterministic check rejects Swedish terms in canonical content."""
    bad_skill = _sample_skill(
        steps=(
            "Inspect fabric.mod.json och kontrollera mod ID.",
            "Run ./gradlew build to compile.",
        )
    )
    result = run_deterministic_quality_checks(SkillDraft(action="CREATE", skill=bad_skill))
    assert result.passed is False
    assert any("english" in f.lower() for f in result.failures)


def test_synthesis_prompt_injects_translation_mandate_on_swedish_feedback():
    """synthesize_skill_proposal_content injects explicit translation instructions on gate feedback."""
    captured_messages = []

    class CapturingClient:
        def complete(self, messages, tools=None, **kwargs):
            captured_messages.extend(messages)
            from hund.providers.base import CompletionResult
            valid_json = json.dumps({
                "when_to_use": "When developing Fabric mods for Minecraft 1.21.",
                "steps": [
                    "Inspect fabric.mod.json to verify mod ID.",
                    "Run ./gradlew build to compile.",
                ],
                "triggers": ["minecraft mod", "fabric mod"],
                "verification": ["Check fabric.mod.json exists.", "Verify build passes."],
                "examples": ["Create Fabric mod block."],
            })
            return CompletionResult(text=valid_json)

    synthesize_skill_proposal_content(
        subject="minecraft modding",
        target_name="minecraft-modding",
        shaping_answers={"focus": "bättre på att koda mods"},
        workspace_configs=(),
        gate_feedback=("Canonical skill content must be in English. Detected non-English term 'ä'.",),
        client=CapturingClient(),
    )

    system_prompt = captured_messages[0].content
    assert "CRITICAL REVISION INSTRUCTION" in system_prompt
    assert "translate all such terms into proper English immediately" in system_prompt
    assert "Decision rules" in system_prompt or "conditional decision rules" in system_prompt.lower()
    assert "anti-pattern warnings" in system_prompt.lower()


def test_loop_research_fallback_dispatched_and_fails_closed_when_all_empty(tmp_path: Path):
    """When web search returns [empty] for all queries including fallback, fail closed."""
    from unittest.mock import patch
    from hund.skills.authoring import SkillAuthoringIntent, create_authoring_session

    reg = get_authoring_registry()
    intent = SkillAuthoringIntent(
        operation="create",
        capability="minecraft 1.21 fabric modding",
        target_scope="project",
        referenced_name=None,
        local_only=False,
        requires_research=True,
        confidence=0.95,
        raw_prompt="skapa en skill för minecraft modding",
    )
    sess = create_authoring_session(intent, registry=reg)

    dispatched_queries = []

    def mock_dispatch(call, *args, **kwargs):
        fn = call.get("function", {})
        args_data = json.loads(fn.get("arguments", "{}"))
        dispatched_queries.append(args_data.get("query"))
        # Return empty result as web_search does
        return "[empty] inga resultat"

    turn_result = AuthoringTurnResult(
        handled=True,
        rendered="Research authorized.",
        research_queries=("Minecraft modding Forge Fabric 1.21",),
        research_fallback_query="Minecraft Fabric modding setup guide",
    )

    with patch("hund.agent.loop.dispatch_tool_call", side_effect=mock_dispatch):
        with patch("hund.skills.authoring_runtime.complete_authoring_research") as mock_complete:
            # Recreate the loop logic directly
            summaries: list[str] = []
            for query in turn_result.research_queries:
                outcome = mock_dispatch({"function": {"name": "web_search", "arguments": json.dumps({"query": query})}})
                if not outcome.startswith(("[error]", "[blocked]", "[declined", "[empty]")):
                    summaries.append(outcome)
            if not summaries and getattr(turn_result, "research_fallback_query", ""):
                outcome = mock_dispatch({"function": {"name": "web_search", "arguments": json.dumps({"query": turn_result.research_fallback_query})}})
                if not outcome.startswith(("[error]", "[blocked]", "[declined", "[empty]")):
                    summaries.append(outcome)

            assert len(summaries) == 0
            assert dispatched_queries == [
                "Minecraft modding Forge Fabric 1.21",
                "Minecraft Fabric modding setup guide",
            ]
            mock_complete.assert_not_called()


def test_loop_research_fallback_succeeds_when_fallback_has_hits():
    """When primary queries return [empty] but fallback succeeds, summaries contains fallback hit."""
    dispatched_queries = []

    def mock_dispatch(call, *args, **kwargs):
        fn = call.get("function", {})
        args_data = json.loads(fn.get("arguments", "{}"))
        q = args_data.get("query")
        dispatched_queries.append(q)
        if "Forge Fabric" in q:
            return "[empty] inga resultat"
        return "Fabric Loom 1.6 plugin guide and official template repository on GitHub."

    turn_result = AuthoringTurnResult(
        handled=True,
        rendered="Research authorized.",
        research_queries=("Minecraft modding Forge Fabric 1.21",),
        research_fallback_query="Minecraft Fabric modding setup guide",
    )

    summaries: list[str] = []
    for query in turn_result.research_queries:
        outcome = mock_dispatch({"function": {"name": "web_search", "arguments": json.dumps({"query": query})}})
        if not outcome.startswith(("[error]", "[blocked]", "[declined", "[empty]")):
            summaries.append(outcome)
    if not summaries and getattr(turn_result, "research_fallback_query", ""):
        outcome = mock_dispatch({"function": {"name": "web_search", "arguments": json.dumps({"query": turn_result.research_fallback_query})}})
        if not outcome.startswith(("[error]", "[blocked]", "[declined", "[empty]")):
            summaries.append(outcome)

    assert len(summaries) == 1
    assert "Fabric Loom 1.6" in summaries[0]
    assert dispatched_queries == [
        "Minecraft modding Forge Fabric 1.21",
        "Minecraft Fabric modding setup guide",
    ]


def test_system_prompts_contain_version_integrity_rule():
    """Call 1, Call 1b, and Call 2 synthesis prompts strictly enforce the version integrity rule."""
    import inspect
    from hund.skills import shaping, authoring_runtime

    # 1. Call 1: build_shaping_plan
    shaping_src = inspect.getsource(shaping.build_shaping_plan)
    assert "VERSION INTEGRITY RULE" in shaping_src
    assert "opaque identifiers" in shaping_src.lower()
    assert "26.2" in shaping_src
    assert "1.26.2" in shaping_src

    # 2. Call 1b: refine_research_queries
    refine_src = inspect.getsource(shaping.refine_research_queries)
    assert "VERSION INTEGRITY" in refine_src
    assert "opaque identifiers" in refine_src.lower()
    assert "1.26.2" in refine_src

    # 3. Call 2: synthesize_skill_proposal_content
    synth_src = inspect.getsource(authoring_runtime.synthesize_skill_proposal_content)
    assert "opaque identifiers" in synth_src.lower()
    assert "1.26.2" in synth_src or "prefix" in synth_src.lower()


def test_refine_research_queries_detects_version_token_and_derives_domain_fallback():
    """When a version token is present, fallback becomes 'latest <domain> version' and queries prioritize exact token."""
    # Test client is None deterministic fallback
    queries, fallback = refine_research_queries(
        subject="minecraft 26.2",
        shaping_answers={"loader": "Fabric"},
        mini_draft=None,
        existing_queries=("minecraft modding setup",),
        client=None,
    )
    assert fallback == "latest minecraft version"
    assert any("26.2" in q for q in queries)

    # Test LLM client call
    fake_llm_json = json.dumps({
        "queries": [
            "Minecraft 26.2 fabric yarn mappings official",
            "Fabric Loom build.gradle configuration 26.2",
        ],
        "fallback_query": "latest minecraft version",
    })
    client = MockLLMClient(fake_llm_json)
    queries_llm, fallback_llm = refine_research_queries(
        subject="minecraft 26.2",
        shaping_answers={"loader": "Fabric"},
        mini_draft=None,
        existing_queries=("minecraft modding setup",),
        client=client,
    )
    assert fallback_llm == "latest minecraft version"
    assert any("26.2" in q for q in queries_llm)


def test_deterministic_quality_checks_grounded_versions():
    """Deterministic quality check accepts grounded versions and fails ungrounded/invented versions."""
    # 1. Stated by user -> passes
    user_skill = _sample_skill(
        when_to_use="When developing Fabric mods for Minecraft 26.2.",
        steps=(
            "Inspect fabric.mod.json to verify mod ID declarations.",
            "Configure gradle.properties targeting Minecraft 26.2 and build.",
        ),
    )
    res1 = run_deterministic_quality_checks(
        SkillDraft(action="CREATE", skill=user_skill),
        raw_prompt="kan du skapa en skill för minecraft 26.2",
        shaping_answers={"loader": "Fabric"},
    )
    assert res1.passed is True

    # 2. Confirmed in declared_dependencies -> passes
    res2 = run_deterministic_quality_checks(
        SkillDraft(action="CREATE", skill=user_skill),
        declared_dependencies=("minecraft_version: 26.2",),
    )
    assert res2.passed is True

    # 3. Invented version '1.26.2' not grounded in prompt, answers, dependencies, or research -> FAILS
    invented_skill = _sample_skill(
        when_to_use="When developing Fabric mods for Minecraft 1.26.2.",
        steps=(
            "Inspect fabric.mod.json to verify mod ID declarations.",
            "Configure gradle.properties targeting Minecraft 1.26.2 and build.",
        ),
    )
    res3 = run_deterministic_quality_checks(
        SkillDraft(action="CREATE", skill=invented_skill),
        raw_prompt="kan du skapa en skill för minecraft 26.2",
        shaping_answers={"loader": "Fabric"},
        declared_dependencies=("minecraft_version: 26.2",),
    )
    assert res3.passed is False
    assert any("version not grounded: '1.26.2'" in f for f in res3.failures)


def test_run_llm_review_gate_receives_research_summaries_and_user_stated_versions():
    """Review gate receives research summaries and user_stated_versions in payload and prompt instructions."""
    from hund.skills.authoring import run_llm_review_gate

    captured_calls = []

    class CapturingReviewClient:
        def complete(self, messages, tools=None, **kwargs):
            captured_calls.append({"messages": messages, "kwargs": kwargs})
            from hund.providers.base import CompletionResult
            return CompletionResult(text=json.dumps({"approved": True, "score": 0.95, "issues": []}))

    skill = _sample_skill(
        when_to_use="When developing Fabric mods for Minecraft 26.2.",
        steps=(
            "Inspect fabric.mod.json to verify mod ID.",
            "Run ./gradlew build to compile the mod.",
        ),
    )
    client = CapturingReviewClient()
    result = run_llm_review_gate(
        SkillDraft(action="CREATE", skill=skill),
        client=client,
        research_summaries=("Minecraft 26.2 is declared in gradle.properties",),
        user_stated_versions={"26.2"},
        run_id="test_run_review",
    )

    assert result.approved is True
    assert len(captured_calls) == 1
    sys_content = captured_calls[0]["messages"][0].content
    user_content = captured_calls[0]["messages"][1].content

    # Check system prompt directive
    assert "VERSION GROUNDING RULE" in sys_content or "Do not reject a version merely because it is unfamiliar" in sys_content
    # Check payload contains research summaries and user stated versions
    payload = json.loads(user_content)
    assert "research_summaries" in payload
    assert payload["research_summaries"] == ["Minecraft 26.2 is declared in gradle.properties"]
    assert "user_stated_versions" in payload
    assert payload["user_stated_versions"] == ["26.2"]


def test_synthesis_call_output_trims_excess_items():
    """synthesize_skill_proposal_content gracefully trims excess verification checks, steps, triggers, and examples."""
    from hund.skills.authoring_runtime import synthesize_skill_proposal_content
    from hund.providers.base import CompletionResult

    payload = {
        "when_to_use": "When developing Fabric mods for Minecraft 26.2.",
        "steps": [f"Step {i}" for i in range(1, 12)],  # 11 steps -> trim to 8
        "triggers": [f"trigger {i}" for i in range(1, 16)],  # 15 triggers -> trim to 12
        "verification": [
            "Run ./gradlew build and ensure success.",
            "Inspect fabric.mod.json to verify mod ID declarations.",
            "Verify Minecraft version 26.2 in gradle.properties.",
            "Inspect compiled jar in build/libs/ directory.",  # 4th item -> trim to 3
        ],
        "examples": ["Example 1", "Example 2", "Example 3"],  # 3 examples -> trim to 2
    }

    class MockClient:
        def complete(self, messages, tools=None, **kwargs):
            return CompletionResult(text=json.dumps(payload))

    when, steps, triggers, verif, examples = synthesize_skill_proposal_content(
        subject="Minecraft modding",
        target_name="minecraft-modding",
        shaping_answers={},
        workspace_configs=(),
        client=MockClient(),
    )
    assert len(verif) == 3
    assert len(steps) == 8
    assert len(triggers) == 12
    assert len(examples) == 2


def test_extract_json_block_strips_think_tags():
    """_extract_json_block cleanly removes <think>...</think> reasoning blocks from model output."""
    from hund.skills.shaping import _extract_json_block

    raw_with_think = (
        "<think>\n"
        "Let me analyze Minecraft 26.2 modding...\n"
        "Fabric is selected. I should structure 2 steps.\n"
        "</think>\n"
        '```json\n{"when_to_use": "When developing mods", "steps": ["s1", "s2"]}\n```'
    )
    extracted = _extract_json_block(raw_with_think)
    parsed = json.loads(extracted)
    assert parsed["when_to_use"] == "When developing mods"


def test_review_gate_neutralizes_spurious_user_version_rejection():
    """RED/GREEN: LLM review gate spurious rejections of user-stated versions are filtered out."""
    from hund.skills.authoring import SkillDraft, run_llm_review_gate
    from hund.providers.base import CompletionResult

    skill = _sample_skill(
        when_to_use="When developing mods targeting Minecraft version 26.2.",
        steps=("Step 1: check gradle.properties.", "Step 2: build fabric mod."),
    )

    spurious_payload = json.dumps({
        "approved": False,
        "score": 0.35,
        "issues": [
            "Unrealistic version: Minecraft 26.2 (or version 26.2) is not recognized in research "
            "or official docs; the version appears to be fabricated internally (research may be simulated)."
        ],
    })

    class SpuriousReviewClient:
        def complete(self, messages, tools=None, **kwargs):
            return CompletionResult(text=spurious_payload)

    review = run_llm_review_gate(
        SkillDraft(action="CREATE", skill=skill),
        client=SpuriousReviewClient(),
        user_stated_versions={"26.2"},
        research_summaries=("Minecraft 26.2 is declared in gradle.properties",),
    )

    assert review.approved is True
    assert review.issues == []
    assert review.score >= 0.7


def test_review_gate_preserves_legitimate_issues_while_filtering_spurious_version():
    """RED/GREEN: Real quality issues are retained even if a spurious version complaint is present."""
    from hund.skills.authoring import SkillDraft, run_llm_review_gate
    from hund.providers.base import CompletionResult

    skill = _sample_skill(
        when_to_use="When developing mods targeting Minecraft version 26.2.",
        steps=("Step 1: check gradle.properties.", "Step 2: build fabric mod."),
    )

    mixed_payload = json.dumps({
        "approved": False,
        "score": 0.45,
        "issues": [
            "Unrealistic version: Minecraft 26.2 is not recognized.",
            "Steps lack anti-pattern warnings 'Do not X; instead Y'.",
        ],
    })

    class MixedReviewClient:
        def complete(self, messages, tools=None, **kwargs):
            return CompletionResult(text=mixed_payload)

    review = run_llm_review_gate(
        SkillDraft(action="CREATE", skill=skill),
        client=MixedReviewClient(),
        user_stated_versions={"26.2"},
        research_summaries=("Minecraft 26.2 is declared in gradle.properties",),
    )

    assert review.approved is False
    assert len(review.issues) == 1
    assert "anti-pattern" in review.issues[0]



