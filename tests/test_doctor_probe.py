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
