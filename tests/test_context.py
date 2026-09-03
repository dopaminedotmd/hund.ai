"""Context compression v1 — deterministisk, ingen provider."""
from __future__ import annotations

from hund.agent.context import (
    DEFAULT_KEEP_RECENT,
    DEFAULT_MAX_TOKENS,
    compress,
    estimate_tokens,
    maybe_compress,
)
from hund.providers.base import Message


def _msgs(n: int) -> list[Message]:
    out = [Message(role="system", content="SYSTEM")]
    for i in range(n):
        out.append(Message(role="user", content=f"turn {i} " * 10))
        out.append(Message(role="assistant", content=f"svar {i} " * 10))
    return out


def test_short_session_not_compressed():
    msgs = _msgs(2)
    res = compress(msgs, keep_recent=6)
    assert res.compressed is False
    assert res.dropped_turns == 0
    assert res.messages == msgs


def test_long_session_drops_middle_keeps_system_and_recent():
    msgs = _msgs(20)  # 1 system + 40 turns
    res = compress(msgs, keep_recent=6)
    assert res.compressed is True
    assert res.dropped_turns > 0
    # system bevarad + marker + initial user-turn + 6 recent
    assert res.messages[0].role == "system"
    assert res.messages[0].content.startswith("SYSTEM")
    assert res.messages[1].role == "system"
    assert res.messages[1].content.startswith("[KOMPRIMERAD")
    assert res.messages[2].role == "user"
    assert res.messages[2].content.startswith("turn 0")
    assert len(res.messages) == 1 + 1 + 1 + 6
    # senaste user-turnen bevarad (näst sista = user, sista = assistant)
    assert res.messages[-2].content.startswith("turn 19")


def test_compression_marks_tool_output_as_data():
    msgs = _msgs(20)
    res = compress(msgs, keep_recent=6)
    assert "OBTRODD DATA" in res.messages[1].content
    assert "ej instruktioner" in res.messages[1].content.lower()


def test_compression_note_not_accumulated_on_recompress():
    msgs = _msgs(20)
    once = compress(msgs, keep_recent=6)
    twice = compress(once.messages, keep_recent=6)
    # noten får ej läggas till igen (den gamla tas bort och ny läggs till, så den finns bara en gång)
    assert twice.messages[1].content.count("[KOMPRIMERAD") == 1


def test_maybe_compress_respects_threshold():
    msgs = _msgs(20)
    # tröskel 0 → alltid komprimera
    res = maybe_compress(msgs, max_tokens=0)
    assert res.compressed is True
    # tröskel enorm → ingen komprimering
    res2 = maybe_compress(msgs, max_tokens=10**9)
    assert res2.compressed is False


def test_estimate_tokens_positive_and_grows():
    small = [Message(role="user", content="hej")]
    big = [Message(role="user", content="x" * 4000)]
    assert estimate_tokens(small) <= estimate_tokens(big)
    assert estimate_tokens(big) >= 900


def test_system_plus_recent_preserved_after_compression_order():
    msgs = _msgs(10)
    res = compress(msgs, keep_recent=4)
    # första = system, andra = marker, tredje = primary task, sedan de 4 senaste i ordning
    assert res.messages[0].role == "system"
    assert res.messages[1].role == "system"
    assert res.messages[2].role == "user"
    assert res.messages[2].content.startswith("turn 0")
    assert [m.role for m in res.messages[3:]] == ["user", "assistant", "user", "assistant"]


def test_default_threshold_is_96k_and_keep_recent_is_12():
    assert DEFAULT_MAX_TOKENS == 96_000
    assert DEFAULT_KEEP_RECENT == 12


def test_initial_user_turn_preserved_without_duplicates():
    msgs = [
        Message(role="system", content="SYS"),
        Message(role="user", content="CRITICAL USER GOAL"),
        Message(role="assistant", content="resp 1"),
        Message(role="user", content="turn 2"),
        Message(role="assistant", content="resp 2"),
        Message(role="user", content="turn 3"),
        Message(role="assistant", content="resp 3"),
        Message(role="user", content="turn 4"),
        Message(role="assistant", content="resp 4"),
    ]
    res = compress(msgs, keep_recent=2)
    assert res.compressed is True
    # Initial user goal must be preserved at index 2
    assert res.messages[2].role == "user"
    assert res.messages[2].content == "CRITICAL USER GOAL"
    # Recent turns must not duplicate the initial user turn
    user_contents = [m.content for m in res.messages if m.role == "user"]
    assert user_contents.count("CRITICAL USER GOAL") == 1



def test_deterministic_same_input_same_output():
    msgs = _msgs(15)
    a = compress(msgs, keep_recent=6)
    b = compress(msgs, keep_recent=6)
    assert [m.content for m in a.messages] == [m.content for m in b.messages]


def test_context_compression_payload_shape():
    msgs = _msgs(20)
    tokens_before = estimate_tokens(msgs)
    res = maybe_compress(msgs, max_tokens=0)
    payload = {
        "turns_dropped": res.dropped_turns,
        "tokens_before": tokens_before,
        "tokens_after": res.tokens,
        "method": "llm" if "via LLM" in res.messages[1].content else "deterministic",
    }
    assert res.compressed is True
    assert payload["turns_dropped"] > 0
    assert payload["tokens_before"] >= payload["tokens_after"]
    assert payload["method"] == "deterministic"


def test_compression_never_starts_with_orphan_tool_message():
    """If keep_recent slices into the middle of a tool sequence, it must not start with role='tool'."""
    msgs = [
        Message(role="system", content="SYSTEM"),
        Message(role="user", content="old user"),
        Message(role="assistant", content="old resp"),
        Message(role="user", content="run tool"),
        Message(role="assistant", content="", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]),
        Message(role="tool", content="tool output 1", tool_call_id="c1"),
        Message(role="tool", content="tool output 2", tool_call_id="c1"),
        Message(role="assistant", content="done tool"),
        Message(role="user", content="final question"),
    ]
    # Slicing with keep_recent=3 would land on index 6 (tool output 2) if unconstrained
    res = compress(msgs, keep_recent=3)
    # First message after system marker must not be 'tool'
    first_non_system = res.messages[2]
    assert first_non_system.role != "tool"

