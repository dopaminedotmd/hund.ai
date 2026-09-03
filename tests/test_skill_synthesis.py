"""RED/GREEN tests for Gate 2 Task 2: Provider-based Synthesis & Craft Rules."""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from hund.providers.base import CompletionResult
from hund.skills.authoring import (
    LocalSkillProposal,
    MiniDraftData,
    ResearchSourceRef,
    SynthesisCallOutput,
)
from hund.skills.authoring_runtime import synthesize_skill_proposal_content
from hund.skills.factory import SkillFactory
from hund.skills.loader import load_builtins
from hund.skills.scope import ScopeResolution


class _FakeSynthesisClient:
    def __init__(self, response_text: str, raise_exc: Exception | None = None):
        self._response_text = response_text
        self._raise_exc = raise_exc
        self.last_messages = None

    def complete(self, messages, tools=None, **kwargs):
        if self._raise_exc:
            raise self._raise_exc
        self.last_messages = messages
        return CompletionResult(text=self._response_text)


def test_synthesis_pydantic_schema_enforces_bounds_and_forbids_extra():
    """RED/GREEN: Pydantic 2 extra='forbid' and typed bounds on all 5 fields."""
    valid_data = {
        "when_to_use": "When diagnosing Kubernetes CrashLoopBackOff pod failures and restarts.",
        "steps": [
            "Inspect pod status and recent restart events using kubectl describe.",
            "Fetch previous container logs using kubectl logs --previous.",
            "Analyze exit code and OOMKilled indicators to isolate failure cause.",
        ],
        "triggers": [
            "crashloop",
            "k8s crashloopbackoff",
            "pod restarting",
        ],
        "verification": [
            "Pod logs and termination message confirm root cause exit code.",
            "Diagnostic report specifies whether crash is application panic or OOM.",
        ],
        "examples": [
            "CrashLoopBackOff with ExitCode 137 identified as OOMKilled.",
        ],
    }
    output = SynthesisCallOutput.model_validate(valid_data)
    assert len(output.steps) == 3
    assert len(output.triggers) == 3
    assert len(output.verification) == 2
    assert len(output.examples) == 1

    # 1. Extra field is forbidden
    bad_extra = dict(valid_data, extra_field="untrusted")
    with pytest.raises(ValidationError):
        SynthesisCallOutput.model_validate(bad_extra)

    # 2. when_to_use too short (< 20 chars)
    bad_wtu = dict(valid_data, when_to_use="Too short.")
    with pytest.raises(ValidationError):
        SynthesisCallOutput.model_validate(bad_wtu)

    # 3. steps bounds (must be 2-8)
    bad_steps_short = dict(valid_data, steps=["Only one step."])
    with pytest.raises(ValidationError):
        SynthesisCallOutput.model_validate(bad_steps_short)

    bad_steps_long = dict(valid_data, steps=[f"Step {i}" for i in range(10)])
    with pytest.raises(ValidationError):
        SynthesisCallOutput.model_validate(bad_steps_long)

    # 4. triggers bounds (must be 1-12)
    bad_triggers_empty = dict(valid_data, triggers=[])
    with pytest.raises(ValidationError):
        SynthesisCallOutput.model_validate(bad_triggers_empty)

    bad_triggers_long = dict(valid_data, triggers=[f"trig {i}" for i in range(15)])
    with pytest.raises(ValidationError):
        SynthesisCallOutput.model_validate(bad_triggers_long)

    # 5. verification bounds (must be 2-3)
    bad_verif_short = dict(valid_data, verification=["One check."])
    with pytest.raises(ValidationError):
        SynthesisCallOutput.model_validate(bad_verif_short)

    bad_verif_long = dict(valid_data, verification=[f"Check {i}" for i in range(5)])
    with pytest.raises(ValidationError):
        SynthesisCallOutput.model_validate(bad_verif_long)


def test_synthesis_trigger_contract_permits_unicode_spaces_and_deduplicates():
    """RED/GREEN: Trigger contract permits Swedish chars and spaces, normalizes and dedupes."""
    data = {
        "when_to_use": "When reviewing Swedish pull requests for release gate compliance.",
        "steps": [
            "Granska ändringar mot checklistan för releasen noggrant.",
            "Verifiera att alla säkerhetskrav och tester passerar grönt.",
        ],
        "triggers": [
            "  granska   pr  ",
            "Granska PR",  # Casefold duplicate
            "släpp-checklista",
            "ärendetriage",
        ],
        "verification": [
            "Checklista för releasen är fullständigt ifylld utan avvikelser.",
            "Testsvit och säkerhetsgrind rapporterar 0 fel.",
        ],
        "examples": [
            "PR med missade tester flaggas och blockeras från merge.",
        ],
    }
    output = SynthesisCallOutput.model_validate(data)
    # Deduped case-insensitively and normalized: "granska pr", "släpp-checklista", "ärendetriage"
    assert len(output.triggers) == 3
    assert "granska pr" in output.triggers or "Granska PR" in output.triggers
    assert "släpp-checklista" in output.triggers
    assert "ärendetriage" in output.triggers


def test_synthesis_replaces_v1_keyword_buckets_and_invokes_provider():
    """RED/GREEN: No hardcoded keyword buckets; provider is called with craft rules and data."""
    valid_payload = json.dumps({
        "when_to_use": "When resolving Rust lifetime errors and borrow checker conflicts.",
        "steps": [
            "Analyze compiler error E0597 or E0502 to identify borrowed value scope.",
            "Refactor code to introduce explicit lifetimes, scoped clones, or restructured ownership.",
            "Run cargo check to confirm borrow checker resolves without regressions.",
        ],
        "triggers": [
            "rust lifetime",
            "borrow checker error",
            "rust borrow issue",
        ],
        "verification": [
            "cargo check completes with 0 lifetime or borrowing errors.",
            "Memory safety guarantees preserved without unsafe blocks.",
        ],
        "examples": [
            "E0597 resolved by introducing lifetime parameter 'a on struct reference.",
        ],
    })
    client = _FakeSynthesisClient(valid_payload)
    mini_draft = MiniDraftData(
        when_to_use="When resolving Rust lifetime errors and borrow checker conflicts.",
        steps=("Analyze compiler error.", "Refactor ownership."),
    )

    when_to_use, steps, triggers, verification, examples = synthesize_skill_proposal_content(
        subject="rust borrow checker",
        target_name="rust-borrow-checker",
        shaping_answers={"focus": "Resolve borrow checker lifetime conflicts"},
        workspace_configs=("Cargo.toml",),
        client=client,
        mini_draft=mini_draft,
    )

    assert "Rust lifetime errors" in when_to_use
    assert len(steps) == 3
    assert "cargo check" in steps[2]
    assert len(triggers) == 3
    assert len(verification) == 2
    assert len(examples) == 1

    # Verify client received craft rules in system prompt and untrusted data in user prompt
    assert client.last_messages is not None
    system_msg = client.last_messages[0]
    user_msg = client.last_messages[1]
    assert "canonical skill synthesis engine" in system_msg.content
    assert "1. Define one narrow capability" in system_msg.content
    assert "untrusted_data" in user_msg.content
    assert "rust borrow checker" in user_msg.content


def test_synthesis_fails_closed_without_client_or_on_invalid_output():
    """RED/GREEN: Synthesis fails closed on missing client or invalid output (no fallback)."""
    # 1. Missing client raises ValueError
    with pytest.raises(ValueError, match="Provider client required"):
        synthesize_skill_proposal_content(
            subject="git rebase",
            target_name="git-rebase",
            shaping_answers={},
            workspace_configs=(),
            client=None,
        )

    # 2. Invalid JSON from client raises ValidationError
    bad_client = _FakeSynthesisClient('{"invalid": "json format"}')
    with pytest.raises(ValidationError):
        synthesize_skill_proposal_content(
            subject="git rebase",
            target_name="git-rebase",
            shaping_answers={},
            workspace_configs=(),
            client=bad_client,
        )


def test_builtin_skill_authoring_json_has_six_canonical_craft_rules():
    """RED/GREEN: skill-authoring.json contains exactly the 6 canonical craft rules."""
    builtins = load_builtins()
    authoring_skill = next((s for s in builtins if s.name == "skill-authoring"), None)
    assert authoring_skill is not None
    assert authoring_skill.immutable is True
    assert len(authoring_skill.steps) == 6
    assert "narrow capability" in authoring_skill.steps[0]
    assert "2–8 concrete ordered steps" in authoring_skill.steps[1]
    assert "1–12 precise routing triggers" in authoring_skill.steps[2]
    assert "1–2 realistic golden examples" in authoring_skill.steps[3]
    assert "2–3 binary verification checks" in authoring_skill.steps[4]
    assert "English and never add secrets" in authoring_skill.steps[5]


def test_factory_build_from_proposal_attaches_lineage_event_ids():
    """RED/GREEN: SkillFactory.build_from_proposal accepts and attaches created_from_event_ids."""
    proposal = LocalSkillProposal(
        name="rust-checker",
        domain="rust",
        intent="rust borrow checker",
        scope="project",
        steps=("Analyze E0597.", "Fix lifetime."),
        required_tools=(),
        when_to_use="When resolving Rust lifetime errors and borrow checker conflicts.",
        triggers=("rust lifetime",),
        verification=("cargo check passes.", "No unsafe blocks introduced."),
        examples=("E0597 resolved cleanly.",),
    )
    resolution = ScopeResolution(
        status="RESOLVED",
        target_name="rust-checker",
        target_scope="project",
        action="CREATE",
    )
    draft = SkillFactory().build_from_proposal(
        proposal,
        resolution,
        created_from_event_ids=("event_run_12345",),
    )
    assert draft.skill.created_from_event_ids == ("event_run_12345",)
    assert draft.skill.examples == ("E0597 resolved cleanly.",)


def test_synthesis_shaping_answers_derive_technical_name_and_consistent_safety():
    """RED/GREEN: shaping answers {'style': 'minimal', 'content': 'ui'} yield technical name and consistent safety_level."""
    valid_payload = json.dumps({
        "when_to_use": "When editing index.html and designing minimal UI interfaces.",
        "steps": [
            "Write file index.html with minimal typography and intentional whitespace.",
            "Edit file styles.css with deliberate contrast and zero marketing slop.",
        ],
        "triggers": [
            "minimal ui",
            "minimal html ui",
        ],
        "verification": [
            "Browser renders minimal typography without layout distortion.",
            "File edits preserve clean CSS spacing hierarchy.",
        ],
        "examples": [
            "Minimalist dashboard UI created with intentional typography.",
        ],
    })
    client = _FakeSynthesisClient(valid_payload)
    shaping = {"style": "minimal", "content": "ui"}

    when_to_use, steps, triggers, verification, examples = synthesize_skill_proposal_content(
        subject="extremt hög design value",
        target_name="extremt-hog-design-value",
        shaping_answers=shaping,
        workspace_configs=(),
        client=client,
    )

    assert client.last_messages is not None
    system_msg = client.last_messages[0].content
    user_data = json.loads(client.last_messages[1].content)["untrusted_data"]

    # Verify anti-slop rules in system prompt
    assert "Anti-slop and concrete design standards" in system_msg
    assert "typography" in system_msg
    assert "spacing" in system_msg

    # Verify derived technical name in payload
    derived_name = user_data["target_name"]
    assert "hog" not in derived_name
    assert "extremt" not in derived_name
    assert "minimal" in derived_name and "ui" in derived_name

    # Build proposal and verify factory enforces write_file/edit_file and confirm_for_write
    proposal = LocalSkillProposal(
        name=derived_name,
        domain="design",
        intent="extremt hög design value",
        scope="project",
        steps=tuple(steps),
        required_tools=(),
        when_to_use=when_to_use,
        triggers=tuple(triggers),
        verification=tuple(verification),
        examples=tuple(examples),
    )
    resolution = ScopeResolution(
        status="RESOLVED",
        target_name=derived_name,
        target_scope="project",
        action="CREATE",
    )
    draft = SkillFactory().build_from_proposal(proposal, resolution)
    assert "write_file" in draft.skill.required_tools
    assert "edit_file" in draft.skill.required_tools
    assert draft.skill.safety_level == "confirm_for_write"


def test_skill_naming_filters_buzzwords_and_generic_verbs_track6_v2():
    from hund.skills.scope import derive_technical_skill_name

    name_se = derive_technical_skill_name("designa html sidor i världsklass")
    assert name_se in ("design-html-pages", "html-pages")
    assert "designar" not in name_se
    assert "sidor" not in name_se
    assert "varldsklass" not in name_se
    assert "världsklass" not in name_se
    assert name_se != "designar-html-sidor-varldsklass"

    name_en = derive_technical_skill_name("design html pages world class")
    assert name_en in ("design-html-pages", "html-pages")
    assert "world" not in name_en
    assert "class" not in name_en
    assert name_en != "design-html-pages-world-class"

    name_shaped = derive_technical_skill_name(
        "designa html sidor i världsklass",
        shaping_answers={"style": "minimal", "content": "ui"},
    )
    assert "minimal" in name_shaped or "ui" in name_shaped
    assert "varldsklass" not in name_shaped
    assert "sidor" not in name_shaped

