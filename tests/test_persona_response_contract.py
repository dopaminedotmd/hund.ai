"""Regression tests for aligned runtime and canonical response contracts."""
from pathlib import Path

from hund.agent.response_policy import get_response_policy_rules
from hund.persona import get_compact_voice_contract


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_contract_has_adaptive_completeness_and_no_signoff_rule():
    contract = get_compact_voice_contract()
    assert "så kort som möjligt och så komplett som nödvändigt" in contract.lower()
    assert "be inte användaren om en uppgift" in contract.lower()
    assert "1–4" not in contract
    assert "1-4" not in contract
    assert len(contract) <= 1500


def test_policy_languages_have_same_semantics_without_fixed_line_limit():
    swedish = "\n".join(get_response_policy_rules(language="sv"))
    english = "\n".join(get_response_policy_rules(language="en"))
    assert "så kort som möjligt och så komplett som nödvändigt" in swedish.lower()
    assert "as short as possible and as complete as necessary" in english.lower()
    assert "be användaren om en uppgift" in swedish.lower()
    assert "ask the user for a task" in english.lower()
    assert "1-4" not in swedish + english
    assert "1–4" not in swedish + english


def test_canonical_persona_and_bible_share_response_truth():
    canonical = (ROOT / "hund/assets/hund-system/hund.md").read_text(encoding="utf-8")
    bible = (ROOT / "HUND_COMPLETE_BIBLE.md").read_text(encoding="utf-8")
    for document in (canonical, bible):
        lowered = document.lower()
        assert "as short as possible and as complete as necessary" in lowered
        assert "do not ask the user for a task" in lowered
        assert "1–4" not in document
        assert "1-4" not in document
        assert "state direction" not in lowered


def test_dead_final_detection_flags_unexecuted_tool_promise():
    from hund.agent.narrative_validation import detect_unexecuted_tool_intent

    tools = ["terminal", "read_file", "write_file"]

    # Swedish intent markers
    assert detect_unexecuted_tool_intent("Låt hund använda terminal för att kontrollera status.", tools)
    assert detect_unexecuted_tool_intent("hund ska köra read_file för att läsa konfigurationen.", tools)
    assert detect_unexecuted_tool_intent("Hund kör terminal to inspect files", tools)

    # English intent markers
    assert detect_unexecuted_tool_intent("Let hund use read_file to inspect the file.", tools)
    assert detect_unexecuted_tool_intent("I will use write_file to save the changes.", tools)
    assert detect_unexecuted_tool_intent("terminal to check process output", tools)

    # Code fence signal
    assert detect_unexecuted_tool_intent("Här är lösningen:\n```python\nprint('hello')\n```", tools)

    # Clean narrative answers without tool intent
    assert not detect_unexecuted_tool_intent("Hund har verifierat ändringen och alla tester passerar.", tools)
    assert not detect_unexecuted_tool_intent("Terminalen rapporterade inga fel.", tools)
    assert not detect_unexecuted_tool_intent("", tools)
    assert not detect_unexecuted_tool_intent("Låt hund köra", [])


def test_loop_correction_max_one_retry():
    from unittest.mock import MagicMock
    from hund.agent.loop import _agent_turn
    from hund.providers.base import Message

    console = MagicMock()
    client = MagicMock()

    call_count = 0
    def mock_stream(messages, tools):
        nonlocal call_count
        call_count += 1
        return ["Låt hund använda terminal för att kontrollera status."]

    client.stream.side_effect = mock_stream

    mock_result = MagicMock()
    mock_result.tool_calls = []
    mock_result.finish_reason = "stop"
    mock_result.prompt_tokens = 10
    mock_result.completion_tokens = 10
    mock_result.latency_ms = 50
    client.last_result = mock_result

    engine = MagicMock()
    engine.workspace_root = ROOT
    cfg = MagicMock()

    messages = [Message(role="user", content="Kolla status")]

    schemas = [{"type": "function", "function": {"name": "terminal"}}]

    _agent_turn(console, client, messages, schemas, engine, cfg, "test-session")

    # Should have called stream exactly twice (initial attempt + exactly 1 retry)
    assert call_count == 2

    # Check that system correction prompt was injected
    system_msgs = [m for m in messages if getattr(m, "role", "") == "system"]
    assert any(
        "You announced intent to use a tool, but emitted no tool call." in getattr(m, "content", "")
        for m in system_msgs
    )


def test_self_representation_does_not_expose_third_person_mechanics():
    """Verify that self-representation skill guidance forbids exposing third-person mechanics."""
    from hund.skills.loader import get_skill

    skill = get_skill("self-representation")
    assert skill is not None
    assert "rita dig" in skill.triggers
    assert "logotyp" in skill.triggers
    assert any("4EBCD5" in step for step in skill.steps)
    assert any("E3E3E4" in step for step in skill.steps)
    assert any("▄▄" in step for step in skill.steps)

    mechanics_phrases = [
        "tänker i tredje person",
        "tredje person - observerar",
        "speaking in third person",
    ]
    for phrase in mechanics_phrases:
        assert phrase not in skill.when_to_use.lower()
        for step in skill.steps:
            assert phrase not in step.lower()
    assert any("NEVER explain, expose, or mention internal mechanics" in s for s in skill.steps)
