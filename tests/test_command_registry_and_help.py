"""Tests verifying that CommandSpec registry, dispatch, autocomplete, and /help remain in 100% sync."""
from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from rich.console import Console

from hund.ui.command_spec import (
    COMMAND_REGISTRY,
    CommandSpec,
    get_all_command_names,
    get_autocomplete_metas,
    get_categorized_commands,
    get_command_spec,
    suggest_similar_command,
)
from hund.ui.commands import COMMANDS, CommandContext, cmd_help, cmd_profile, dispatch_command
from hund.ui.input import resolve_slash_command
from hund.ui.screen_render import render_help_inline


def test_command_registry_and_dispatch_table_consistency() -> None:
    """Verify every registered command has a valid dispatch handler in COMMANDS."""
    for spec in COMMAND_REGISTRY:
        if spec.is_hidden or spec.is_planned:
            continue
        # Primary name must be present in dispatch table
        assert spec.name in COMMANDS, f"Missing dispatch handler for command: /{spec.name}"
        # All aliases must be present in dispatch table
        for alias in spec.aliases:
            assert alias in COMMANDS, f"Missing dispatch handler for alias: /{alias} of /{spec.name}"


def test_autocomplete_metas_sync_with_registry() -> None:
    """Verify autocomplete metadata matches active commands in COMMAND_REGISTRY."""
    metas = get_autocomplete_metas()
    for spec in COMMAND_REGISTRY:
        if spec.is_hidden or spec.is_planned:
            assert f"/{spec.name}" not in metas
        else:
            assert f"/{spec.name}" in metas
            assert metas[f"/{spec.name}"] == spec.short_description


def test_get_command_spec_lookups() -> None:
    """Test lookup helper by name, alias, slash prefix, and case."""
    # By primary name
    spec = get_command_spec("system")
    assert spec is not None
    assert spec.name == "system"
    assert spec.category == "SYSTEM & HEALTH"

    # With slash and upper case
    spec2 = get_command_spec("/DOCTOR")
    assert spec2 is not None
    assert spec2.name == "doctor"

    # By alias
    spec3 = get_command_spec("?")
    assert spec3 is not None
    assert spec3.name == "help"

    spec4 = get_command_spec("/sys")
    assert spec4 is not None
    assert spec4.name == "system"

    # Non-existent
    assert get_command_spec("nonexistent_xyz") is None


def test_suggest_similar_command() -> None:
    """Verify typo suggestions for misspelled commands."""
    assert suggest_similar_command("doktor") == "doctor"
    assert suggest_similar_command("systm") == "system"
    assert suggest_similar_command("modle") == "model"
    assert suggest_similar_command("/skils") == "skills"
    assert suggest_similar_command("totally_unknown_12345") is None


def test_render_help_inline_content_and_progression_rules() -> None:
    """Verify /help contains canonical HOW HUND GROWS frame and all base stats."""
    help_text = render_help_inline(width=80)

    # Base Stats frame
    assert "HOW HUND GROWS" in help_text
    assert "CLR" in help_text and "Clarity" in help_text
    assert "PRC" in help_text and "Precision" in help_text
    assert "EFF" in help_text and "Efficiency" in help_text
    assert "END" in help_text and "Endurance" in help_text
    assert "MAS" in help_text and "Mastery" in help_text
    assert "Stats change only from recorded outcomes" in help_text

    # Categories
    assert "SESSION & CONTEXT" in help_text
    assert "SYSTEM & HEALTH" in help_text
    assert "MODELS & ACCESS" in help_text
    assert "CAPABILITIES" in help_text
    assert "GENERAL" in help_text

    # Key commands present
    assert "/history" in help_text
    assert "/system" in help_text
    assert "/doctor" in help_text
    assert "/model" in help_text
    assert "/auth" in help_text
    assert "/skills" in help_text
    assert "/tools" in help_text


def test_render_help_inline_narrow_width_never_omits_commands() -> None:
    """Verify /help stacks commands on narrow widths without dropping any command."""
    narrow_text = render_help_inline(width=40)
    for spec in COMMAND_REGISTRY:
        if not spec.is_hidden and not spec.is_planned:
            assert f"/{spec.name}" in narrow_text, f"Command /{spec.name} missing in narrow help view!"


def test_render_help_inline_ascii_mode() -> None:
    """Verify ASCII fallback rendering."""
    ascii_text = render_help_inline(width=80, ascii_only=True)
    assert "+- HOW HUND GROWS" in ascii_text
    assert "/system" in ascii_text
    assert "Type a command for details * Tab completes commands" in ascii_text


def test_cmd_profile_migration_notice() -> None:
    """Verify /profile prints migration notice directing users to /system."""
    buf = io.StringIO()
    console = Console(file=buf, color_system=None, width=80)
    ctx = CommandContext(console=console, rt=SimpleNamespace(), state=SimpleNamespace())

    cmd_profile(ctx, [])
    output = buf.getvalue()
    assert "System information has moved to /system" in output
    assert "/system" in output
    assert "Named context profiles are planned" in output


def test_dispatch_command_typo_handling() -> None:
    """Verify dispatch_command handles typos with helpful suggestions."""
    buf = io.StringIO()
    console = Console(file=buf, color_system=None, width=80)
    ctx = CommandContext(console=console, rt=SimpleNamespace(), state=SimpleNamespace())

    # Misspelled command
    dispatched = dispatch_command("/doktor", ctx)
    assert dispatched is True
    output = buf.getvalue()
    assert "unknown command: /doktor" in output
    assert "Did you mean /doctor?" in output


def test_find_command_by_topic() -> None:
    """Verify topic-based command metadata lookup."""
    from hund.ui.command_spec import find_command_by_topic

    spec_skills = find_command_by_topic("hur ser jag denna skillen?")
    assert spec_skills is not None
    assert spec_skills.name == "skills"

    spec_skills2 = find_command_by_topic("vad kan jag göra i /skills?")
    assert spec_skills2 is not None
    assert spec_skills2.name == "skills"

    spec_history = find_command_by_topic("hur ser jag tidigare svar i sessionen?")
    assert spec_history is not None
    assert spec_history.name == "history"

    spec_clear = find_command_by_topic("hur rensar jag skärmen?")
    assert spec_clear is not None
    assert spec_clear.name == "clear"

    spec_unknown = find_command_by_topic("random unrelated question about bananas")
    assert spec_unknown is None
