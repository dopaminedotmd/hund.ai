"""Tests for Local Engine — mock subprocess and HTTP calls."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hund.local.engine import (
    LocalEngine,
    LocalEngineError,
    EngineNotRunningError,
    EngineTimeoutError,
    EngineStartError,
)


# ── Model resolution ───────────────────────────────────────────────


def test_resolve_model_none():
    engine = LocalEngine()
    assert engine.model_path is None


def test_resolve_model_explicit(tmp_path):
    gguf = tmp_path / "model.gguf"
    gguf.write_text("gguf-data")
    engine = LocalEngine(model_path=str(gguf))
    assert engine.model_path == gguf.resolve()


def test_resolve_model_not_found():
    engine = LocalEngine(model_path="/nonexistent/model.gguf")
    assert engine.model_path is None


def test_resolve_model_from_env(tmp_path, monkeypatch):
    gguf = tmp_path / "env_model.gguf"
    gguf.write_text("data")
    monkeypatch.setenv("HUND_LOCAL_MODEL_PATH", str(gguf))
    engine = LocalEngine()
    assert engine.model_path == gguf.resolve()


# ── Health ──────────────────────────────────────────────────────────


def test_health_not_running():
    engine = LocalEngine()
    with pytest.raises(EngineNotRunningError):
        engine.health()


def test_is_running_false_when_no_process():
    engine = LocalEngine()
    assert engine.is_running is False


def test_is_running_true_when_process_alive():
    engine = LocalEngine()
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    engine._process = mock_proc
    assert engine.is_running is True


def test_is_running_false_when_process_dead():
    engine = LocalEngine()
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    engine._process = mock_proc
    assert engine.is_running is False


# ── Stop ────────────────────────────────────────────────────────────


def test_stop_not_running():
    engine = LocalEngine()
    result = engine.stop()
    assert result["status"] == "not_running"


def test_stop_running_engine():
    engine = LocalEngine()
    mock_proc = MagicMock()
    engine._process = mock_proc
    result = engine.stop()
    assert result["status"] == "stopped"
    assert engine._process is None


# ── Start (mocked) ──────────────────────────────────────────────────


@patch("hund.local.engine.LocalEngine._resolve_model")
@patch("hund.local.engine.LocalEngine._find_llama_server")
@patch("subprocess.Popen")
def test_start_no_model(Popen, find_llama, resolve_model):
    resolve_model.return_value = None
    engine = LocalEngine()
    with pytest.raises(EngineStartError, match="No GGUF model found"):
        engine.start()


@patch("hund.local.engine.LocalEngine._resolve_model")
@patch("hund.local.engine.LocalEngine._find_llama_server")
@patch("subprocess.Popen")
def test_start_no_llama_server(Popen, find_llama, resolve_model):
    resolve_model.return_value = Path("/tmp/model.gguf")
    find_llama.return_value = None
    engine = LocalEngine()
    with pytest.raises(EngineStartError, match="llama-server not found"):
        engine.start()


# ── Complete (mocked HTTP) ──────────────────────────────────────────


def test_complete_not_running():
    engine = LocalEngine()
    with pytest.raises(EngineNotRunningError):
        engine.complete([{"role": "user", "content": "hi"}])


@patch("hund.local.engine.urllib.request.urlopen")
def test_complete_http_call(urlopen):
    engine = LocalEngine()
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    engine._process = mock_proc

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "choices": [{"message": {"content": "Hello!"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }).encode("utf-8")
    urlopen.return_value = mock_resp

    result = engine.complete([{"role": "user", "content": "hi"}])
    assert result["text"] == "Hello!"
    assert result["finish_reason"] == "stop"
    assert result["prompt_tokens"] == 10


@patch("hund.local.engine.urllib.request.urlopen")
def test_complete_timeout(urlopen):
    engine = LocalEngine()
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    engine._process = mock_proc
    urlopen.side_effect = TimeoutError("timed out")

    with pytest.raises(EngineTimeoutError):
        engine.complete([{"role": "user", "content": "hi"}])


@patch.object(LocalEngine, "_http_get")
def test_health_http(http_get):
    http_get.return_value = {"version": "b1234", "status": "ok"}
    engine = LocalEngine()
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    engine._process = mock_proc

    health = engine.health()
    assert health["running"] is True
    assert health["llama_version"] == "b1234"


# ── Properties ─────────────────────────────────────────────────────


def test_port_default():
    engine = LocalEngine()
    assert engine.port == 8080


def test_port_custom():
    engine = LocalEngine(port=9090)
    assert engine.port == 9090
