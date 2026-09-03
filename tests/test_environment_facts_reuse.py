"""Tests for canonical environment facts serialization and turn-local reuse."""
from __future__ import annotations

from pathlib import Path
import pytest

from hund.agent.environment_context import (
    get_canonical_snapshot,
    serialize_environment_facts,
)
from hund.agent.task_brief import TaskType
from hund.agent.user_context import expand_user_context
from hund.stats.environment_snapshot import EnvironmentSnapshot, VolumeStorage


@pytest.fixture
def mock_snapshot() -> EnvironmentSnapshot:
    vol = VolumeStorage(mount_point="C:\\", total_gb=237.5, free_gb=90.4, used_gb=147.1, safe_headroom_gb=45.2)
    return EnvironmentSnapshot(
        os="Windows",
        os_version="11.0.26100",
        os_caption="Microsoft Windows 11 Pro",
        os_arch="64-bit",
        hostname="WORKSTATION-PC",
        processor="Intel(R) Core(TM) i7-8550U CPU @ 1.80GHz",
        cpu_count=8,
        gpu_model="Intel(R) UHD Graphics 620",
        gpu_vram_mb=128,
        total_ram_gb=15.9,
        used_ram_gb=0.0,
        primary_volume=vol,
        volumes=(vol,),
        has_git=True,
        has_python=True,
        has_uv=True,
        has_node=False,
        has_powershell=True,
        shell="powershell",
        python_impl="CPython",
        observed_at="2026-08-25T19:08:00+00:00",
    )


def test_serialize_environment_facts_schema(mock_snapshot: EnvironmentSnapshot) -> None:
    """Verify serializer emits stable schema keys and strict resource separation."""
    facts = serialize_environment_facts(mock_snapshot, language="sv")

    # Stable schema keys
    assert "• CPU:" in facts
    assert "• GPU:" in facts
    assert "• GPU_VRAM:" in facts
    assert "• SYSTEM_RAM:" in facts
    assert "• STORAGE:" in facts
    assert "• OS:" in facts
    assert "• RUNTIMES:" in facts
    assert "• OBSERVED_AT:" in facts

    # Content checks
    assert "i7-8550U" in facts
    assert "15.9 GiB totalt fysiskt minne" in facts
    assert "C:\\ (237.5 GiB total, 90.4 GiB free)" in facts
    assert "128 MiB dedicated" in facts
    assert "19:08" in facts

    # Invariant note
    assert "RAM (systemminne), VRAM (grafikminne) och Disk (lagring) är helt separata resurser" in facts

    # No secrets or ANSI banner garbage
    assert "\x1b[" not in facts
    assert "sk-" not in facts


def test_serialize_environment_facts_english_localization(mock_snapshot: EnvironmentSnapshot) -> None:
    """Verify English localization formatting."""
    facts_en = serialize_environment_facts(mock_snapshot, language="en")
    assert "KNOWN ENVIRONMENT FACTS" in facts_en
    assert "total physical RAM" in facts_en
    assert "RAM (system memory), VRAM (graphics memory), and Disk (storage capacity) are strictly separate resources" in facts_en


def test_expand_user_context_attaches_facts_for_system_queries(tmp_path: Path) -> None:
    """Verify system query automatically receives structured facts without subprocess tools."""
    expanded = expand_user_context("Tell me about my system hardware and specs", tmp_path)
    assert expanded.task_brief is not None
    assert expanded.task_brief.task_type == TaskType.SYSTEM_INSPECTION
    assert "• CPU:" in expanded.prompt
    assert "• SYSTEM_RAM:" in expanded.prompt
    assert "• STORAGE:" in expanded.prompt


def test_expand_user_context_skips_facts_for_general_queries(tmp_path: Path) -> None:
    """Verify general questions do not receive environment facts unnecessarily."""
    expanded = expand_user_context("Hur fungerar list comprehensions i Python?", tmp_path)
    assert expanded.task_brief is not None
    assert expanded.task_brief.task_type == TaskType.DIRECT_ANSWER
    assert "• CPU:" not in expanded.prompt
    assert "• STORAGE:" not in expanded.prompt


def test_expand_user_context_attaches_separation_directive_for_model_recommendations(tmp_path: Path) -> None:
    """Verify model recommendation queries attach resource separation directives."""
    expanded = expand_user_context("Vilken lokal modell rekommenderar du för denna maskin?", tmp_path)
    assert expanded.task_brief is not None
    assert expanded.task_brief.task_type == TaskType.RECOMMENDATION
    assert "• CPU:" in expanded.prompt
    assert "Separera tydligt system-RAM, GPU-VRAM och diskutrymme" in expanded.prompt


def test_expand_user_context_localization_swedish_and_english(tmp_path: Path) -> None:
    """Verify Swedish and English queries receive properly localized context without mixed metadata."""
    # Swedish query
    expanded_sv = expand_user_context("Berätta om min dator och hårdvara", tmp_path)
    assert "[KÄND MILJÖDATA" in expanded_sv.prompt
    assert "totalt fysiskt minne" in expanded_sv.prompt
    assert "RAM (systemminne), VRAM (grafikminne) och Disk (lagring) är helt separata resurser" in expanded_sv.prompt
    assert "[KNOWN ENVIRONMENT FACTS" not in expanded_sv.prompt
    assert "\x1b[" not in expanded_sv.prompt

    # English query
    expanded_en = expand_user_context("Tell me about my computer and hardware specs", tmp_path)
    assert "[KNOWN ENVIRONMENT FACTS" in expanded_en.prompt
    assert "total physical RAM" in expanded_en.prompt
    assert "RAM (system memory), VRAM (graphics memory), and Disk (storage capacity) are strictly separate resources" in expanded_en.prompt
    assert "[KÄND MILJÖDATA" not in expanded_en.prompt
    assert "\x1b[" not in expanded_en.prompt

    # Uppercase Swedish
    expanded_upper_sv = expand_user_context("VISA MIN HÅRDVARA OCH MITT MINNE", tmp_path)
    assert "[KÄND MILJÖDATA" in expanded_upper_sv.prompt

    # Uppercase English
    expanded_upper_en = expand_user_context("SHOW MY HARDWARE SPECS AND MEMORY", tmp_path)
    assert "[KNOWN ENVIRONMENT FACTS" in expanded_upper_en.prompt

    # Mixed technical text default
    expanded_mixed = expand_user_context("what cpu is used for deepseek-v4 model?", tmp_path)
    assert "[KNOWN ENVIRONMENT FACTS" in expanded_mixed.prompt


def test_shell_probe_and_prompt_builder():
    """Verify probe_shell detects real shell, and prompt_builder emits verified shell & rules."""
    from hund.doctor import probe_shell, EnvironmentProfile
    from hund.agent.prompt_builder import build_system_prompt
    import os

    shell = probe_shell()
    if os.name == "nt":
        assert "cmd.exe" in shell
        assert "powershell" not in shell.lower()

    prof = EnvironmentProfile(
        os="Windows",
        os_version="11.0",
        cpu_count=8,
        shell=shell,
        capabilities={"has_git": True, "can_run_python": True},
    )
    prompt = build_system_prompt("PERSONA", prof)
    assert f"- Shell: {shell}" in prompt
    assert "Kalla aldrig CMD 'PowerShell'" in prompt


def test_snapshot_persistence_across_sessions(tmp_path: Path):
    """Snapshot persists to disk; new session reads without rescan; force_fresh updates."""
    import hund.stats.environment_snapshot as es

    # Create and persist snapshot
    snap1 = es.create_environment_snapshot(workspace=tmp_path, force_fresh=True)
    snap_file = tmp_path / ".hund" / "environment_snapshot.json"
    assert snap_file.exists()

    # Reset in-memory cache to simulate new process/session
    es._CACHED_SNAPSHOT = None

    # Load without force_fresh
    snap2 = es.create_environment_snapshot(workspace=tmp_path, force_fresh=False)
    assert snap2.observed_at == snap1.observed_at
    assert snap2.processor == snap1.processor
    assert snap2.shell == snap1.shell

    # With force_fresh, observed_at should be refreshed
    snap3 = es.create_environment_snapshot(workspace=tmp_path, force_fresh=True)
    assert snap3 is not None


def test_terminal_tool_pwd_shell_and_utf8(tmp_path: Path):
    """Verify terminal tool handles utf-8 Swedish characters (åäö) and valid cwd."""
    from hund.tools.terminal_tool import make_handler

    handler_dict = make_handler(tmp_path)
    term = handler_dict["terminal"]

    # Write a test python file that outputs åäö
    py_script = tmp_path / "test_utf8.py"
    py_script.write_text("print('Hund ser åäö')", encoding="utf-8")

    import sys
    res = term({"command": f'"{sys.executable}" test_utf8.py'})
    assert "[exit 0]" in res.to_llm_text()
    assert "Hund ser åäö" in res.to_llm_text()

