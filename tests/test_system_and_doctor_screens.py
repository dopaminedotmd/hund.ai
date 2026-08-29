"""Tests verifying /system environment snapshot and read-only /doctor diagnostic surfaces."""
from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest
from rich.console import Console

from hund.doctor import CheckResult, DoctorReport, diagnose_system
from hund.stats.environment_snapshot import (
    EnvironmentSnapshot,
    VolumeStorage,
    create_environment_snapshot,
)
from hund.ui.commands import CommandContext, cmd_doctor, cmd_system
from hund.ui.screen_render import render_doctor, render_system


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


def test_environment_snapshot_facts_and_changes(mock_snapshot: EnvironmentSnapshot) -> None:
    """Verify EnvironmentSnapshot observation time and change detection."""
    assert mock_snapshot.observation_time_display == "19:08"

    # No changes with identical snapshot
    changes = mock_snapshot.changes_since(mock_snapshot)
    assert "No meaningful hardware or runtime changes detected." in changes[0]

    # Change in CPU
    modified = EnvironmentSnapshot(
        os=mock_snapshot.os,
        os_version=mock_snapshot.os_version,
        os_caption=mock_snapshot.os_caption,
        os_arch=mock_snapshot.os_arch,
        hostname=mock_snapshot.hostname,
        processor="AMD Ryzen 9 7950X 16-Core Processor",
        cpu_count=32,
        gpu_model=mock_snapshot.gpu_model,
        gpu_vram_mb=mock_snapshot.gpu_vram_mb,
        total_ram_gb=64.0,
        used_ram_gb=0.0,
        primary_volume=mock_snapshot.primary_volume,
        volumes=mock_snapshot.volumes,
        has_git=mock_snapshot.has_git,
        has_python=mock_snapshot.has_python,
        has_uv=mock_snapshot.has_uv,
        has_node=mock_snapshot.has_node,
        has_powershell=mock_snapshot.has_powershell,
        shell=mock_snapshot.shell,
        python_impl=mock_snapshot.python_impl,
        observed_at=mock_snapshot.observed_at,
    )
    detected_changes = modified.changes_since(mock_snapshot)
    assert any("CPU changed" in ch for ch in detected_changes)
    assert any("Total RAM changed" in ch for ch in detected_changes)


def test_render_system_layout_and_redaction(mock_snapshot: EnvironmentSnapshot) -> None:
    """Verify /system renders the TUI Facit layout and never leaks private secrets."""
    rendered = render_system(mock_snapshot, width=80, height=24)

    # Frame header
    assert "SYSTEM" in rendered
    assert "observed 19:08" in rendered

    # Sections
    assert "── HARDWARE" in rendered
    assert "i7-8550U" in rendered
    assert "Intel(R) UHD Graphics 620" in rendered
    assert "15.9 GiB total" in rendered
    assert "128 MiB dedicated" in rendered

    assert "── STORAGE" in rendered
    assert "C:\\" in rendered
    assert "237.5 GiB total" in rendered
    assert "90.4 GiB free" in rendered

    assert "── ENVIRONMENT" in rendered
    assert "Windows 11 Pro" in rendered
    assert "PowerShell" in rendered
    assert "Python" in rendered

    # Footer
    assert "[r] Refresh" in rendered

    # Redaction: No API keys, trace IDs, or private paths
    assert "sk-" not in rendered
    assert "trace_" not in rendered


def test_diagnose_system_evaluations() -> None:
    """Verify diagnose_system produces structured CheckResults and summary counts."""
    report = diagnose_system()
    assert isinstance(report, DoctorReport)
    assert len(report.checks) >= 5

    check_names = [c.name for c in report.checks]
    assert "Environment snapshot" in check_names
    assert "Config and recovery" in check_names
    assert "Provider credentials" in check_names
    assert "Learning store" in check_names

    # Summary string format
    assert "passed" in report.summary_text
    assert "warnings" in report.summary_text
    assert "failed" in report.summary_text


def test_render_doctor_view_and_fix_plan() -> None:
    """Verify /doctor screen format, status glyphs, and read-only fix plan."""
    checks = (
        CheckResult(name="Environment snapshot", status="pass", detail="Current"),
        CheckResult(name="Config and recovery", status="pass", detail="Healthy"),
        CheckResult(name="Provider credentials", status="warn", detail="OpenAI needs a key", remedy="Use /auth"),
        CheckResult(name="Learning store", status="pass", detail="Schema current"),
    )
    report = DoctorReport(
        checks=checks,
        fix_plan=("Configure OpenAI API key in /auth",),
    )

    # Standard view
    view = render_doctor(report, width=80, height=24, review_fixes=False)
    assert "DOCTOR" in view
    assert "✓" in view
    assert "!" in view
    assert "OpenAI needs a key" in view
    assert "3 passed · 1 warnings · 0 failed" in view
    assert "[f] Review fixes" in view

    # Never renders raw dataclass representation
    assert "EnvironmentProfile(" not in view

    # View with fixes review (strictly read-only)
    fixes_view = render_doctor(report, width=80, height=24, review_fixes=True)
    assert "RECOMMENDED REPAIR ACTIONS (READ-ONLY)" in fixes_view
    assert "Configure OpenAI API key in /auth" in fixes_view
    assert "Execute proposed commands individually" in fixes_view


def test_render_doctor_ascii_fallback() -> None:
    """Verify /doctor ASCII fallback mode."""
    checks = (
        CheckResult(name="Environment snapshot", status="pass", detail="Current"),
        CheckResult(name="Config and recovery", status="fail", detail="Corrupted", remedy="Reset"),
    )
    report = DoctorReport(checks=checks)
    ascii_view = render_doctor(report, width=80, height=24, ascii_only=True)
    assert "[OK]" in ascii_view
    assert "[X]" in ascii_view
    assert "+ DOCTOR" in ascii_view


def test_cli_cmd_system_and_cmd_doctor_execution() -> None:
    """Test CLI dispatch handlers for /system and /doctor."""
    buf = io.StringIO()
    console = Console(file=buf, color_system=None, width=80)
    ctx = CommandContext(console=console, rt=SimpleNamespace(), state=SimpleNamespace())

    # 1. /system in CLI
    cmd_system(ctx, [])
    sys_out = buf.getvalue()
    assert "SYSTEM" in sys_out
    assert "HARDWARE" in sys_out

    # 2. /system changes in CLI
    buf.seek(0)
    buf.truncate(0)
    cmd_system(ctx, ["changes"])
    changes_out = buf.getvalue()
    assert "ENVIRONMENT CHANGES" in changes_out

    # 3. /doctor in CLI
    buf.seek(0)
    buf.truncate(0)
    cmd_doctor(ctx, [])
    doc_out = buf.getvalue()
    assert "DOCTOR" in doc_out
    assert "Environment snapshot" in doc_out
    assert "passed" in doc_out


def test_parse_nvidia_smi_and_wmi_gpu_output() -> None:
    """Verify GPU VRAM parsing from nvidia-smi and WMI."""
    from hund.doctor import parse_nvidia_smi_output, parse_wmi_gpu_output

    # 1. nvidia-smi with dual GPU (integrated + discrete 11GB GTX 1080 Ti)
    nvidia_raw = "Intel(R) UHD Graphics 620, 128\nNVIDIA GeForce GTX 1080 Ti, 11264\n"
    name, vram_mb = parse_nvidia_smi_output(nvidia_raw)
    assert name == "NVIDIA GeForce GTX 1080 Ti"
    assert vram_mb == 11264

    # 2. WMI with 32-bit wrapped AdapterRAM bytes
    wmi_raw = "4294967295|NVIDIA GeForce GTX 1080 Ti\n134217728|Intel(R) UHD Graphics 620"
    wmi_name, wmi_vram = parse_wmi_gpu_output(wmi_raw)
    assert wmi_name == "NVIDIA GeForce GTX 1080 Ti"
    assert wmi_vram == 4095  # 4294967295 // (1024*1024)
