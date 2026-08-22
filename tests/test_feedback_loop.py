"""Tester för Behavior Feedback Loop — extract, compress, store."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from hund.feedback.extract import extract_lessons
from hund.feedback.compress import compress_lessons, _compress_text, _similarity
from hund.feedback.store import FeedbackStore, _similarity as _store_similarity


# ---------------------------------------------------------------------------
# Hjälp: skapa fejkade TraceEvent-objekt för tester
# ---------------------------------------------------------------------------

class _FakeTraceEvent:
    """Simulerar TraceEvent med de fält extract_lessons läser."""

    def __init__(self, event_type, payload_redacted, actor="hund",
                 tool_name=None, run_id="run-1"):
        self.event_type = event_type
        self.payload_redacted = payload_redacted
        self.actor = actor
        self.tool_name = tool_name
        self.run_id = run_id


# ---------------------------------------------------------------------------
# extract_lessons tester
# ---------------------------------------------------------------------------

def test_extract_tool_errors(monkeypatch):
    """Verktygsfel med error i payload extraheras som tool_error."""
    events = [
        _FakeTraceEvent(
            "tool_call_completed",
            {"error": "gcc: command not found"},
            tool_name="terminal",
        ),
    ]

    def fake_list(session_id, db_path=None):
        return events

    monkeypatch.setattr(
        "hund.feedback.extract.list_events_by_session", fake_list
    )

    lessons = extract_lessons("s1", "r1", "/home/user/project")
    assert len(lessons) >= 1
    tool_errors = [l for l in lessons if l["category"] == "tool_error"]
    assert len(tool_errors) >= 1
    assert "gcc" in tool_errors[0]["raw_text"]
    assert tool_errors[0]["confidence"] == 0.7


def test_extract_verification_fails(monkeypatch):
    """Verifieringsfail med passed=false extraheras som verify_fail."""
    events = [
        _FakeTraceEvent(
            "verification_completed",
            {
                "passed": False,
                "verification_kind": "mypy",
                "command": "mypy src/",
                "exit_code": 1,
            },
        ),
    ]

    def fake_list(session_id, db_path=None):
        return events

    monkeypatch.setattr(
        "hund.feedback.extract.list_events_by_session", fake_list
    )

    lessons = extract_lessons("s1", "r1", "/home/user/project")
    verify_fails = [l for l in lessons if l["category"] == "verify_fail"]
    assert len(verify_fails) >= 1
    assert "mypy" in verify_fails[0]["raw_text"]
    assert verify_fails[0]["confidence"] == 0.6


def test_extract_user_corrections(monkeypatch):
    """Användarkorrigeringar med nyckelord extraheras."""
    events = [
        _FakeTraceEvent("tool_call_completed", {"output": "ok"}, tool_name="terminal"),
        _FakeTraceEvent(
            "user_message",
            {"content": "nej, använd pytest istället för unittest"},
            actor="user",
        ),
    ]

    def fake_list(session_id, db_path=None):
        return events

    monkeypatch.setattr(
        "hund.feedback.extract.list_events_by_session", fake_list
    )

    lessons = extract_lessons("s1", "r1", "/home/user/project")
    corrections = [l for l in lessons if l["category"] == "user_correction"]
    assert len(corrections) >= 1
    assert "pytest" in corrections[0]["raw_text"]
    assert corrections[0]["confidence"] == 0.9


def test_extract_success_patterns(monkeypatch):
    """Verifiering som lyckas efter tidigare fail ger success_pattern."""
    events = [
        _FakeTraceEvent(
            "verification_completed",
            {"passed": False, "verification_kind": "pytest", "command": "pytest"},
        ),
        _FakeTraceEvent(
            "verification_completed",
            {"passed": True, "verification_kind": "pytest", "command": "pytest -x"},
        ),
    ]

    def fake_list(session_id, db_path=None):
        return events

    monkeypatch.setattr(
        "hund.feedback.extract.list_events_by_session", fake_list
    )

    lessons = extract_lessons("s1", "r1", "/home/user/project")
    successes = [l for l in lessons if l["category"] == "success_pattern"]
    assert len(successes) >= 1
    assert "pytest" in successes[0]["raw_text"]


def test_extract_empty_session(monkeypatch):
    """Tom session ger inga lärdomar."""

    def fake_list(session_id, db_path=None):
        return []

    monkeypatch.setattr(
        "hund.feedback.extract.list_events_by_session", fake_list
    )

    lessons = extract_lessons("s1", "r1", "/home/user/project")
    assert lessons == []


def test_extract_handles_db_error(monkeypatch):
    """Fel i list_events_by_session hanteras — returnerar tom lista."""

    def fake_list(session_id, db_path=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(
        "hund.feedback.extract.list_events_by_session", fake_list
    )

    lessons = extract_lessons("s1", "r1", "/home/user/project")
    assert lessons == []


# ---------------------------------------------------------------------------
# compress_lessons tester
# ---------------------------------------------------------------------------

def test_compress_groups_by_category():
    """Komprimering grupperar och tar topp-1 per kategori."""
    raw = [
        {
            "category": "tool_error",
            "raw_text": "terminal: gcc not found",
            "confidence": 0.7,
            "domain": "c",
            "workspace_id": "/ws",
        },
        {
            "category": "tool_error",
            "raw_text": "terminal: make failed",
            "confidence": 0.5,
            "domain": "c",
            "workspace_id": "/ws",
        },
        {
            "category": "user_correction",
            "raw_text": "nej, använd cmake istället för make",
            "confidence": 0.9,
            "domain": "c",
            "workspace_id": "/ws",
        },
    ]
    result = compress_lessons(raw, domain="c", limit=3)
    assert 1 <= len(result) <= 3
    # user_correction har högst confidence → bör vara med
    categories = {r["category"] for r in result}
    assert "user_correction" in categories


def test_compress_respects_limit():
    """Komprimering respekterar limit."""
    raw = [
        {"category": "tool_error", "raw_text": "e1", "confidence": 0.9, "domain": "x", "workspace_id": "/w"},
        {"category": "verify_fail", "raw_text": "e2", "confidence": 0.8, "domain": "x", "workspace_id": "/w"},
        {"category": "user_correction", "raw_text": "e3", "confidence": 0.7, "domain": "x", "workspace_id": "/w"},
        {"category": "success_pattern", "raw_text": "e4", "confidence": 0.6, "domain": "x", "workspace_id": "/w"},
    ]
    result = compress_lessons(raw, domain="x", limit=2)
    assert len(result) <= 2


def test_compress_empty_input():
    """Tom indata ger tom utdata."""
    assert compress_lessons([], domain="x") == []


def test_compressed_text_max_200_chars():
    """Varje komprimerad lärdom är max 200 tecken."""
    long_text = "x" * 500
    compressed = _compress_text(long_text)
    assert len(compressed) <= 200


def test_compress_text_truncation():
    """Komprimering trunkerar lång text smart."""
    text = "Detta är en väldigt lång text som beskriver ett fel i detalj " * 10
    compressed = _compress_text(text)
    assert len(compressed) <= 200
    assert compressed.endswith("...")


# ---------------------------------------------------------------------------
# _similarity tester
# ---------------------------------------------------------------------------

def test_similarity_identical():
    """Identiska strängar ger similarity 1.0."""
    assert _similarity("npm install failed", "npm install failed") == 1.0


def test_similarity_different():
    """Helt olika strängar ger similarity 0.0."""
    assert _similarity("npm install failed", "python test") == 0.0


def test_similarity_empty():
    """Tomma strängar ger similarity 0.0."""
    assert _similarity("", "") == 0.0
    assert _similarity("abc", "") == 0.0


# ---------------------------------------------------------------------------
# FeedbackStore tester
# ---------------------------------------------------------------------------

def test_store_creates_table(tmp_path):
    """FeedbackStore skapar behavior_lessons-tabellen automatiskt."""
    db = tmp_path / "test_hund.db"
    store = FeedbackStore(db_path=db)
    rows = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='behavior_lessons'"
    ).fetchall()
    assert len(rows) == 1
    store.close()


def test_store_and_query_lessons(tmp_path):
    """Lagra lärdomar och hämta top-K."""
    db = tmp_path / "test_hund.db"
    store = FeedbackStore(db_path=db)

    lessons = [
        {
            "lesson_text": "Kolla att gcc finns före kompilering.",
            "category": "tool_error",
            "confidence": 0.7,
            "domain": "c",
            "session_id": "s1",
            "workspace_id": "/ws/c",
        },
        {
            "lesson_text": "Användaren föredrar pytest över unittest.",
            "category": "user_correction",
            "confidence": 0.9,
            "domain": "c",
            "session_id": "s1",
            "workspace_id": "/ws/c",
        },
    ]
    stored = store.store_lessons(lessons)
    assert stored == 2

    result = store.query_top_lessons("/ws/c", "c", limit=5)
    assert len(result) == 2
    # Högst confidence först (user_correction 0.9 > tool_error 0.7)
    assert result[0]["category"] == "user_correction"
    store.close()


def test_store_deduplication(tmp_path):
    """Liknande lärdomar uppdateras istället för att dupliceras."""
    db = tmp_path / "test_hund.db"
    store = FeedbackStore(db_path=db)

    # Första lagringen
    store.store_lessons([
        {
            "lesson_text": "Kolla att gcc finns installerat",
            "category": "tool_error",
            "confidence": 0.7,
            "domain": "c",
            "session_id": "s1",
            "workspace_id": "/ws/c",
        },
    ])

    # Andra lagringen — liknande text
    store.store_lessons([
        {
            "lesson_text": "Kolla att gcc finns installerat fore bygge",
            "category": "tool_error",
            "confidence": 0.8,
            "domain": "c",
            "session_id": "s2",
            "workspace_id": "/ws/c",
        },
    ])

    result = store.query_top_lessons("/ws/c", "c", limit=5)
    # Borde vara 1 (uppdaterad), inte 2
    assert len(result) == 1
    # seen_count borde vara 2
    assert result[0]["seen_count"] == 2
    store.close()


def test_store_query_respects_limit(tmp_path):
    """query_top_lessons respekterar limit."""
    db = tmp_path / "test_hund.db"
    store = FeedbackStore(db_path=db)

    lessons = [
        {"lesson_text": f"Lärdom {i}", "category": "tool_error",
         "confidence": 0.5 + i * 0.1, "domain": "py",
         "session_id": "s1", "workspace_id": "/ws/py"}
        for i in range(10)
    ]
    store.store_lessons(lessons)

    result = store.query_top_lessons("/ws/py", "py", limit=3)
    assert len(result) == 3
    store.close()


def test_store_query_empty_workspace(tmp_path):
    """Fråga mot tom workspace ger tom lista."""
    db = tmp_path / "test_hund.db"
    store = FeedbackStore(db_path=db)
    result = store.query_top_lessons("/ws/nonexistent", "rust", limit=5)
    assert result == []
    store.close()


def test_store_similarity():
    """Store-similarity identifierar liknande strängar."""
    assert _store_similarity("npm install failed", "npm install failed again") > 0.5
    assert _store_similarity("python test", "rust compile") < 0.3
    # Högre än 0.7 för dedupliceringströskeln
    assert _store_similarity("Kolla att gcc finns installerat", "Kolla att gcc finns installerat fore bygge") > 0.7
