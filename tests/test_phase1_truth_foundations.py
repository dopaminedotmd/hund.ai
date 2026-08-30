"""Tests for Phase 1 Truth Foundations: CommandSpec, EnvironmentSnapshot, Endurance v2, and receipts."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from hund.domains.xp import (
    EVENT_CROSS_SESSION_REUSE,
    EVENT_DISCOVERY,
    EVENT_SAME_TASK_REUSE,
    EVENT_VALIDATION_PROMOTION,
    format_xp_reason,
)
from hund.stats.base_stats import compute_endurance
from hund.stats.environment_snapshot import (
    EnvironmentSnapshot,
    VolumeStorage,
    create_environment_snapshot,
)
from hund.ui.command_spec import (
    COMMAND_REGISTRY,
    CommandSpec,
    get_autocomplete_metas,
    get_categorized_commands,
    get_command_spec,
)


# --- 1. CommandSpec Tests ---

def test_command_registry_contains_core_commands() -> None:
    expected = ["history", "session", "compress", "clear", "system", "doctor", "usage", "stats", "model", "auth", "skills", "tools", "help", "exit"]
    names = [spec.name for spec in COMMAND_REGISTRY]
    for exp in expected:
        assert exp in names, f"Expected /{exp} in COMMAND_REGISTRY"


def test_command_spec_lookup() -> None:
    # Look up by primary name with/without slash
    spec = get_command_spec("auth")
    assert spec is not None
    assert spec.name == "auth"
    assert spec.category == "MODELS & ACCESS"

    spec2 = get_command_spec("/auth")
    assert spec2 == spec

    # Look up by alias
    spec_exit = get_command_spec("q")
    assert spec_exit is not None
    assert spec_exit.name == "exit"


def test_categorized_commands_grouping() -> None:
    grouped = get_categorized_commands()
    assert "SESSION & CONTEXT" in grouped
    assert "SYSTEM & HEALTH" in grouped
    assert "MODELS & ACCESS" in grouped
    assert "CAPABILITIES" in grouped


def test_autocomplete_metas() -> None:
    metas = get_autocomplete_metas()
    assert "/auth" in metas
    assert "/system" in metas
    assert "/help" in metas
    assert "/exit" in metas


# --- 2. EnvironmentSnapshot Tests ---

def test_environment_snapshot_creation(tmp_path: Path) -> None:
    snapshot = create_environment_snapshot(workspace=tmp_path, force_fresh=True)
    assert isinstance(snapshot, EnvironmentSnapshot)
    assert snapshot.os != ""
    assert snapshot.total_ram_gb > 0
    assert snapshot.primary_volume.total_gb > 0
    assert snapshot.primary_volume.safe_headroom_gb >= 0
    assert snapshot.gpu_vram_gb >= 0


def test_environment_snapshot_profile_compat() -> None:
    snapshot = create_environment_snapshot(force_fresh=True)
    prof = snapshot.to_profile_compat(workspace="c:\\test")
    assert prof.os == snapshot.os
    assert prof.processor == snapshot.processor
    assert prof.workspace == "c:\\test"


# --- 3. Endurance v2 Tests ---

def test_endurance_v2_collecting_evidence_below_threshold(tmp_path: Path) -> None:
    # With no sessions, should return Collecting evidence
    stat = compute_endurance(home=tmp_path, min_sample_threshold=3)
    assert stat["value"] is None
    assert stat.get("status_text") == "Collecting evidence"


def test_endurance_v3_messages_alone_never_grant_progress(tmp_path: Path) -> None:
    from hund.agent import sessions

    for _ in range(3):
        session_id = sessions.create(home=tmp_path)
        for role in ("user", "assistant", "user", "assistant"):
            sessions.add_message(session_id, role, "message", home=tmp_path)

    stat = compute_endurance(home=tmp_path, min_sample_threshold=3)

    assert stat["value"] is None
    assert stat["progress"] == 0
    assert stat["status_text"] == "Collecting evidence"


# --- 4. Progression Receipt Reasons Tests ---

def test_format_xp_reasons() -> None:
    assert format_xp_reason(EVENT_DISCOVERY) == "discovery"
    assert format_xp_reason(EVENT_SAME_TASK_REUSE) == "verified same-task reuse"
    assert format_xp_reason(EVENT_CROSS_SESSION_REUSE) == "verified cross-session reuse"
    assert format_xp_reason(EVENT_VALIDATION_PROMOTION) == "validation promotion"
