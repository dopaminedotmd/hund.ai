"""Tests for TaskBrief modeling and deterministic task policy classification."""
from __future__ import annotations

from pathlib import Path
import pytest

from hund.agent.task_brief import ResponseFormat, TaskBrief, TaskType
from hund.agent.task_policy import classify_task


def test_task_brief_immutability() -> None:
    """Verify TaskBrief is an immutable frozen dataclass."""
    brief = TaskBrief(
        task_type=TaskType.DIRECT_ANSWER,
        requested_outcome="Explain concept",
        confidence=0.85,
        scope="general",
        preferred_format=ResponseFormat.PROSE,
    )
    assert brief.task_type == TaskType.DIRECT_ANSWER
    assert brief.preferred_format == ResponseFormat.PROSE
    with pytest.raises(Exception):
        brief.confidence = 0.99  # type: ignore[misc]


def test_classify_system_inspection_queries() -> None:
    """Verify system and hardware queries are classified as SYSTEM_INSPECTION."""
    queries = [
        "what hardware do I have?",
        "tell me about my system",
        "show me my CPU and RAM specs",
        "vad har jag för hårdvara på datorn?",
        "hur mycket ram har jag?",
        "visa information om min processor och disk",
        "system specs for this machine",
    ]
    for q in queries:
        brief = classify_task(q)
        assert brief.task_type == TaskType.SYSTEM_INSPECTION, f"Failed for query: {q}"
        assert brief.needs_environment_facts is True
        assert brief.environment_freshness == "session_static"
        assert brief.scope == "system"
        assert brief.confidence >= 0.90


def test_classify_recommendation_queries() -> None:
    """Verify local model and resource queries are classified as RECOMMENDATION."""
    queries = [
        "which local model can I run on this computer?",
        "recommend a local LLM for my hardware",
        "can I run llama 3 on this PC?",
        "vilken lokal modell passar bäst på min dator?",
        "rekommendera en lokal modell",
        "kan jag köra deepseek lokalt?",
        "passar qwen på denna dator?",
    ]
    for q in queries:
        brief = classify_task(q)
        assert brief.task_type == TaskType.RECOMMENDATION, f"Failed for query: {q}"
        assert brief.needs_environment_facts is True
        assert brief.environment_freshness == "dynamic_refresh"
        assert brief.requires_disk_vram_separation is True
        assert brief.preferred_format == ResponseFormat.LIST
        assert brief.requires_uncertainty_disclosure is True


def test_classify_diagnosis_queries() -> None:
    """Verify health and doctor queries are classified as DIAGNOSIS."""
    queries = [
        "run doctor on my system",
        "kör doctor",
        "kolla system health",
        "kör diagnos",
    ]
    for q in queries:
        brief = classify_task(q)
        assert brief.task_type == TaskType.DIAGNOSIS, f"Failed for query: {q}"
        assert brief.needs_environment_facts is True


def test_classify_web_research_queries() -> None:
    """Verify time-sensitive and version queries are classified as WEB_RESEARCH."""
    queries = [
        "what is the latest version of Python?",
        "senaste versionen av Next.js",
        "when was DeepSeek-V3 released?",
        "aktuella nyheter om OpenAI models",
    ]
    for q in queries:
        brief = classify_task(q)
        assert brief.task_type == TaskType.WEB_RESEARCH, f"Failed for query: {q}"
        assert brief.needs_web_research is True
        assert brief.scope == "external"


def test_classify_code_tasks() -> None:
    """Verify code modification and inspection queries."""
    # Modification
    mod_queries = [
        "create file utils.py with helper functions",
        "skapa en fil som heter test_calc.py",
        "refactor function process_data in my code",
        "fix bug in authentication handler",
    ]
    for q in mod_queries:
        brief = classify_task(q)
        assert brief.task_type == TaskType.LOCAL_CODE_MODIFICATION, f"Failed for: {q}"
        assert brief.needs_workspace_context is True

    # Inspection
    insp_queries = [
        "var ligger funktionen calculate_score?",
        "search for class UserSession in repo",
        "inspect code in @file:main.py",
    ]
    for q in insp_queries:
        brief = classify_task(q)
        assert brief.task_type == TaskType.LOCAL_CODE_INSPECTION, f"Failed for: {q}"
        assert brief.needs_workspace_context is True


def test_classify_direct_answer_fallback() -> None:
    """Verify conceptual questions and ambiguous inputs fall back to DIRECT_ANSWER."""
    queries = [
        "hur fungerar pythagoras sats?",
        "förklara skillnaden mellan async och threading i python",
        "hej hund",
        "tack så mycket",
        "something totally ambiguous and random 12345",
    ]
    for q in queries:
        brief = classify_task(q)
        assert brief.task_type == TaskType.DIRECT_ANSWER, f"Failed for: {q}"
        assert brief.preferred_format == ResponseFormat.PROSE
        assert brief.needs_environment_facts is False


def test_classify_self_knowledge_queries() -> None:
    """Verify stable product/command questions route to SELF_KNOWLEDGE with zero tool needs."""
    queries = [
        "hur ser jag denna skillen?",
        "vad kan jag göra i /skills?",
        "var hanterar jag mina skills?",
        "what does /skills do?",
        "how do I see my skills?",
        "vad gör /doctor?",
        "vilka kommandon finns?",
        "what commands are available?",
    ]
    for q in queries:
        brief = classify_task(q)
        assert brief.task_type == TaskType.SELF_KNOWLEDGE, f"Expected SELF_KNOWLEDGE for query: {q}, got {brief.task_type}"
        assert brief.needs_workspace_context is False, f"Expected no workspace context for: {q}"
        assert brief.needs_environment_facts is False, f"Expected no env facts for: {q}"
        assert brief.needs_web_research is False, f"Expected no web research for: {q}"


def test_diagnostic_and_code_inspection_separation() -> None:
    """Verify diagnostic and code inspection questions do NOT route to SELF_KNOWLEDGE."""
    diag_queries = [
        ("varför syns skillen inte trots active state?", {TaskType.DIAGNOSIS, TaskType.LOCAL_CODE_INSPECTION}),
        ("vilken kod renderar /skills?", {TaskType.LOCAL_CODE_INSPECTION}),
        ("kontrollera installerad version mot source", {TaskType.DIAGNOSIS, TaskType.LOCAL_CODE_INSPECTION}),
    ]
    for q, allowed_types in diag_queries:
        brief = classify_task(q)
        assert brief.task_type != TaskType.SELF_KNOWLEDGE, f"Query '{q}' erroneously classified as SELF_KNOWLEDGE!"
        assert brief.task_type in allowed_types, f"Query '{q}' got {brief.task_type}, expected one of {allowed_types}"
