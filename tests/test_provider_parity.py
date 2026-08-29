"""Tests for multi-provider parity across Claude, OpenAI, Gemini, and Ollama."""
import json
from pathlib import Path
import pytest

from hund.skills.model import BANNED_ACTIONS
from hund.tools.skill_tool import make_handler, parse_create_skill_args
from hund.tools.types import ToolStatus


def test_provider_parity_claude_request_format(tmp_path: Path):
    claude_args = {
        "request": "create a skill for formatting markdown tables",
        "target_scope": "project",
        "desired_disposition": "equip",
    }
    parsed = parse_create_skill_args(claude_args)
    assert parsed.request == "create a skill for formatting markdown tables"
    assert parsed.target_scope == "project"
    assert parsed.desired_disposition == "equip"

    handler = make_handler(home=tmp_path, workspace_path=tmp_path)
    res = handler(claude_args)
    assert res.status is ToolStatus.SUCCESS
    assert "Saved skill" in res.to_llm_text()


def test_provider_parity_openai_request_format(tmp_path: Path):
    openai_args = {
        "request": "create a skill to run unit tests with coverage",
    }
    parsed = parse_create_skill_args(openai_args)
    assert parsed.request == "create a skill to run unit tests with coverage"
    assert parsed.target_scope == "unresolved"
    assert parsed.desired_disposition == "auto"

    handler = make_handler(home=tmp_path, workspace_path=tmp_path)
    res = handler(openai_args)
    assert res.status is ToolStatus.SUCCESS
    assert "Saved skill" in res.to_llm_text()


def test_provider_parity_gemini_format(tmp_path: Path):
    gemini_args = {
        "request": "create a skill for semantic git commit messages",
        "target_scope": "global",
        "desired_disposition": "vault",
    }
    parsed = parse_create_skill_args(gemini_args)
    assert parsed.request == "create a skill for semantic git commit messages"
    assert parsed.target_scope == "global"
    assert parsed.desired_disposition == "vault"

    handler = make_handler(home=tmp_path, workspace_path=tmp_path)
    res = handler(gemini_args)
    assert res.status is ToolStatus.SUCCESS
    assert "Saved skill" in res.to_llm_text()


def test_provider_parity_ollama_legacy_skill_object_format(tmp_path: Path):
    ollama_legacy_args = {
        "skill": {
            "schema_version": 1,
            "name": "ollama-helper",
            "domain": "general",
            "status": "draft",
            "triggers": ["ollama help"],
            "when_to_use": "When using ollama helper.",
            "steps": ["Step 1: check ollama"],
            "required_tools": [],
            "forbidden_actions": list(BANNED_ACTIONS),
            "safety_level": "read_only",
            "verification": ["Verify ollama."],
        }
    }
    parsed = parse_create_skill_args(ollama_legacy_args)
    assert parsed.legacy_skill is not None

    handler = make_handler(home=tmp_path, workspace_path=tmp_path)
    res = handler(ollama_legacy_args)
    assert res.status is ToolStatus.SUCCESS
    assert "Saved skill 'ollama-helper'" in res.to_llm_text()


def test_openai_compatible_protocol_filter_complete():
    from hund.providers.openai_compatible import filter_leaked_protocol

    leaked = "Here is an answer <｜tool calls begin｜>function:write_file{\"path\": \"foo\"}<｜tool calls end｜> with more text."
    filtered = filter_leaked_protocol(leaked)
    assert "<｜tool" not in filtered
    assert "write_file" not in filtered
    assert "Here is an answer  with more text." in filtered


def test_openai_compatible_protocol_filter_stream_cross_chunk():
    from hund.providers.openai_compatible import StreamProtocolFilter

    chunks = [
        "Normal text start. ",
        "Split marker: <｜tool ",
        "calls begin｜>function:read_file{\"path\":\"secret\"}<｜tool ",
        "calls end｜> and continuing text.",
    ]
    stream_filter = StreamProtocolFilter()
    emitted = []
    for chunk in chunks:
        out = stream_filter.feed(chunk)
        if out:
            emitted.append(out)
    final = stream_filter.flush()
    if final:
        emitted.append(final)

    full_output = "".join(emitted)
    assert "<｜tool" not in full_output
    assert "secret" not in full_output
    assert "Normal text start. Split marker:  and continuing text." in full_output


def test_openai_compatible_fullwidth_and_variant_markers():
    from hund.providers.openai_compatible import filter_leaked_protocol

    variants = [
        "prefix ＜｜tool_calls_begin｜＞payload＜｜tool_calls_end｜＞ suffix",
        "prefix <tool_call>{\"name\":\"bash\"}</tool_call> suffix",
        "prefix [TOOL_CALLS]call:something{}[/TOOL_CALLS] suffix",
        "prefix <invoke name=\"test\">args</invoke> suffix",
    ]
    for text in variants:
        filtered = filter_leaked_protocol(text)
        assert "prefix" in filtered
        assert "suffix" in filtered
        assert "payload" not in filtered
        assert "bash" not in filtered
        assert "something" not in filtered
        assert "invoke" not in filtered


def test_openai_compatible_benign_xml_and_code_preserved():
    from hund.providers.openai_compatible import filter_leaked_protocol

    benign = [
        "<div>Hello <b>world</b></div>",
        "if x < 5 and y > 10:\n    return True",
        "def test_tools():\n    return [1, 2, 3]",
        "<tools>configuration block</tools>",
        "Use `[a-z0-9]` for regex match.",
    ]
    for text in benign:
        filtered = filter_leaked_protocol(text)
        assert filtered == text, f"Expected '{text}' to be preserved unchanged, got '{filtered}'"
