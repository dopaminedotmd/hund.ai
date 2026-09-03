"""Tests for Gate A2: Deterministic skill self-knowledge and bare authoring clarification."""
import pytest
from pathlib import Path

from hund.agent.task_brief import TaskBrief, TaskType
from hund.agent.task_policy import classify_task
from hund.agent.response_policy import render_advisory_directives
from hund.skills.authoring import detect_explicit_skill_intent, extract_shaping_questions, SkillAuthoringIntent


class TestSkillEducationalSelfKnowledge:
    @pytest.mark.parametrize(
        "query",
        [
            "Hur fungerar en skill?",
            "Vad är en skill?",
            "Vad är skills?",
            "Hur fungerar skills?",
            "What is a skill?",
            "What are skills?",
            "How do skills work?",
            "Hur fungerar en skill i hund?",
        ],
    )
    def test_educational_queries_classify_as_self_knowledge(self, query: str):
        brief = classify_task(query)
        assert brief.task_type == TaskType.SELF_KNOWLEDGE
        assert not brief.needs_web_research
        assert not brief.needs_workspace_context
        assert not brief.needs_environment_facts

    def test_educational_advisory_directive_prohibits_tools_and_enforces_pedagogy(self):
        brief = classify_task("Hur fungerar en skill?")
        directive = render_advisory_directives(brief, language="sv")
        assert "verktyg" in directive.lower() or "tool" in directive.lower()
        # Advisory instructs tool-free concise pedagogical explanation
        assert "inget verktyg" in directive.lower() or "inga verktyg" in directive.lower() or "zero tool" in directive.lower() or "utan verktyg" in directive.lower() or "pedagogisk" in directive.lower()


class TestBareAuthoringClarification:
    @pytest.mark.parametrize(
        "query",
        [
            "Bygg en skill.",
            "Skapa en skill",
            "Bygg en skill",
            "Skapa en ny skill",
            "Create a skill.",
            "Make a skill",
            "Build a skill",
            "Create a new skill",
        ],
    )
    def test_bare_authoring_detected_with_clarification_or_empty_subject(self, query: str):
        intent = detect_explicit_skill_intent(query)
        # Should either be detected with bare/unspecified capability or handled via authoring route
        assert intent is not None
        assert intent.operation == "create"
        # Capability is empty or generic placeholder requiring clarification
        assert intent.capability in ("", "unspecified", "generic") or intent.requires_clarification is True

    def test_bare_authoring_shaping_yields_clarification_question(self):
        intent = SkillAuthoringIntent(
            operation="create",
            capability="",
            target_scope="unresolved",
            referenced_name=None,
            local_only=True,
            requires_research=False,
            confidence=0.95,
            raw_prompt="Bygg en skill.",
        )
        questions = extract_shaping_questions(intent)
        assert len(questions) >= 1
        assert questions[0].key == "clarification" or "clarification" in questions[0].title.lower() or "vad" in questions[0].title.lower() or "what" in questions[0].title.lower()


class TestQualityGateAndRichSynthesis:
    def test_quality_gate_rejects_hollow_boilerplate(self):
        from hund.skills.authoring import SkillDraft, run_deterministic_quality_checks
        from hund.skills.model import Skill

        hollow_skill = Skill(
            schema_version=1,
            name="marketing",
            domain="general",
            status="draft",
            triggers=("marketing",),
            when_to_use="When the task requires marketing.",
            steps=(
                "Inspect pyproject.toml for requirements relevant to marketing.",
                "Execute marketing using the current project's conventions.",
                "Apply the marketing workflow without overriding unrelated project behavior.",
            ),
            required_tools=(),
            forbidden_actions=(),
            safety_level="read_only",
            verification=("Run the relevant project checks and verify the marketing outcome against the request.",),
            lifecycle_state="draft",
            vault_state="vaulted",
            version="1.0.0",
            capability_id="general/marketing",
            scope="global",
            personal_skill_xp=0,
        )
        draft = SkillDraft(action="CREATE", skill=hollow_skill)
        result = run_deterministic_quality_checks(draft)
        assert not result.passed
        assert any("boilerplate" in f.lower() or "when_to_use" in f.lower() for f in result.failures)

    def test_synthesize_skill_proposal_creates_rich_domain_steps(self):
        import json
        from hund.skills.authoring_runtime import synthesize_skill_proposal_content
        from hund.skills.authoring import SkillDraft, run_deterministic_quality_checks
        from hund.skills.model import BANNED_ACTIONS, Skill
        from hund.providers.base import CompletionResult

        class _SynthesisClient:
            def complete(self, messages, tools=None, **kwargs):
                content = json.dumps({
                    "when_to_use": "When executing structured domain workflows with explicit verification.",
                    "steps": [
                        "Analyze the current state and verify constraints before starting.",
                        "Execute the primary domain procedure with safe defaults.",
                        "Verify outcomes against required operational criteria.",
                    ],
                    "triggers": ["domain task", "domain workflow"],
                    "verification": [
                        "Primary execution logs indicate clean completion.",
                        "Output conforms to expected domain invariants.",
                    ],
                    "examples": ["Execute structured domain operation cleanly."],
                })
                return CompletionResult(text=content, prompt_tokens=100, completion_tokens=50)

        client = _SynthesisClient()
        domains = ["planning-files", "git-rebase", "database-migration", "b2b-outreach", "customer-support"]
        for d in domains:
            when_to_use, steps, triggers, verification, examples = synthesize_skill_proposal_content(
                subject=d,
                target_name=d,
                shaping_answers={},
                workspace_configs=(),
                client=client,
            )
            assert len(steps) >= 3
            assert len(when_to_use) > 30
            assert len(verification) >= 1

            skill = Skill(
                schema_version=1,
                name=d,
                domain="general",
                status="draft",
                triggers=triggers,
                when_to_use=when_to_use,
                steps=steps,
                required_tools=(),
                forbidden_actions=sorted(list(BANNED_ACTIONS)),
                safety_level="read_only",
                verification=verification,
                lifecycle_state="draft",
                vault_state="vaulted",
                version="1.0.0",
                capability_id=f"general/{d}",
                scope="project",
                personal_skill_xp=0,
            )
            draft = SkillDraft(action="CREATE", skill=skill)
            res = run_deterministic_quality_checks(draft)
            assert res.passed, f"Domain {d} failed quality check: {res.failures}"

    def test_markdown_json_parsing_and_memory_inclusion(self):
        from hund.skills.shaping import ShapingCallOutput, build_knowledge_packet, _extract_json_block
        from hund.skills.authoring import SkillAuthoringIntent, LocalInspectionSnapshot

        raw_llm_markdown = (
            "Here is the shaping plan:\n"
            "```json\n"
            "{\n"
            '  "mini_draft": {\n'
            '    "when_to_use": "When managing planning files.",\n'
            '    "steps": ["Step 1: Check ADRs.", "Step 2: Write plan."]\n'
            "  },\n"
            '  "questions": [\n'
            "    {\n"
            '      "key": "spec_depth",\n'
            '      "title": "Specification Depth",\n'
            '      "help_text": "Choose the level of technical detail for planning files",\n'
            '      "options": ["High detail with ADRs", "Standard task breakdown", "High-level milestones"],\n'
            '      "default_option": "High detail with ADRs"\n'
            "    }\n"
            "  ],\n"
            '  "research_queries": []\n'
            "}\n"
            "```\n"
        )
        json_str = _extract_json_block(raw_llm_markdown)
        parsed = ShapingCallOutput.model_validate_json(json_str)
        assert parsed is not None
        assert len(parsed.questions) == 1
        assert parsed.questions[0].key == "spec_depth"
        assert parsed.questions[0].title == "Specification Depth"
        assert len(parsed.questions[0].options) == 3

        intent = detect_explicit_skill_intent("Skapa en skill för planeringsfiler.")
        assert intent is not None
        snapshot = LocalInspectionSnapshot(
            workspace_name="hund",
            workspace_root="c:/test",
            config_files_found=("pyproject.toml",),
            relevant_files=(),
            registered_tools=("read_file", "write_file"),
            scoped_skills=(),
            declared_dependencies=("pytest", "prompt_toolkit"),
        )
        packet = build_knowledge_packet(
            intent=intent,
            snapshot=snapshot,
            user_memories=["User prefers strict TypeScript and test-driven development."],
            project_memories=["Repository uses Next.js app router with ADRs in docs/decisions."],
        )
        assert "user_profile" in packet
        assert "User prefers strict TypeScript" in packet["user_profile"][0]
        assert "project_profile" in packet
        assert "Repository uses Next.js" in packet["project_profile"][0]
