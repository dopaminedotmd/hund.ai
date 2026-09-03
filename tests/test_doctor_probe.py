"""Tests for the single-round-trip system probe (doctor D4)."""

from __future__ import annotations

import json

from hund import doctor


def test_probe_system_parses_json(monkeypatch):
    payload = {
        "caption": "Microsoft Windows 11 Pro",
        "arch": "64-bit",
        "ram_bytes": 17179869184,
        "gpus": [{"adapterRAM": 4294967295, "name": "NVIDIA GeForce GTX 1080 Ti"}],
    }
    calls = []
    monkeypatch.setattr(
        doctor, "_powershell", lambda script: calls.append(script) or json.dumps(payload)
    )
    data = doctor.probe_system()
    assert calls == [doctor._SYSTEM_PROBE_SCRIPT]
    assert data == payload


def test_probe_system_malformed_json_falls_back(monkeypatch):
    monkeypatch.setattr(doctor, "_powershell", lambda script: "not json {")
    assert doctor.probe_system() == {}


def test_detect_gpu_from_structured_wmi(monkeypatch):
    monkeypatch.setattr(doctor, "_which", lambda name: False)
    gpus = [
        {"adapterRAM": 134217728, "name": "Intel(R) UHD Graphics 620"},
        {"adapterRAM": 4294967295, "name": "NVIDIA GeForce GTX 1080 Ti"},
    ]
    name, vram = doctor._detect_gpu(wmi_gpus=gpus)
    assert name == "NVIDIA GeForce GTX 1080 Ti"
    assert vram == 4095  # 4294967295 // (1024*1024)


def test_profile_environment_uses_single_powershell_call(monkeypatch):
    payload = {"caption": "X", "arch": "64-bit", "ram_bytes": 8589934592, "gpus": []}
    ps_calls = []
    monkeypatch.setattr(
        doctor, "_powershell", lambda script: ps_calls.append(script) or json.dumps(payload)
    )
    monkeypatch.setattr(doctor, "_which", lambda name: False)

    prof = doctor.profile_environment()

    assert len(ps_calls) == 1
    assert prof.os_caption == "X"
    assert prof.total_ram_gb == 8.0
    assert prof.gpu_model == ""


# --- Track 21: context window doctor check (Masterplan A STEG 0) ---


def test_context_window_check_flags_overclaim() -> None:
    """Configured window above the model's true window must warn."""
    from hund.config import HundConfig

    cfg = HundConfig()
    cfg.provider.model = "deepseek-chat"
    cfg.provider.context_window = 1_000_000
    result = doctor._check_context_window(cfg)
    assert result.name == "Context window"
    assert result.status == "warn"
    assert "1,000,000" in result.detail
    assert "131,072" in result.detail
    assert result.remedy


def test_context_window_check_passes_when_truthful() -> None:
    from hund.config import HundConfig

    cfg = HundConfig()
    cfg.provider.model = "deepseek-chat"
    cfg.provider.context_window = 131_072
    result = doctor._check_context_window(cfg)
    assert result.status == "pass"


def test_context_window_check_unknown_model_is_unverified() -> None:
    from hund.config import HundConfig

    cfg = HundConfig()
    cfg.provider.model = "mystery-model"
    result = doctor._check_context_window(cfg)
    assert result.status == "pass"
    assert "unverified" in result.detail.lower()


def test_diagnose_system_includes_context_window_check() -> None:
    """The /doctor report must contain the context window truthfulness check."""
    from types import SimpleNamespace

    from hund.config import HundConfig

    cfg = HundConfig()
    report = doctor.diagnose_system(SimpleNamespace(cfg=cfg))
    names = [c.name for c in report.checks]
    assert "Context window" in names
