"""Local Inference Engine — manage llama.cpp subprocess for local model inference.

Uses llama.cpp's built-in HTTP server (llama-server) as a subprocess.
No Python bindings required. Communicates via HTTP API.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


LOCAL_ENGINE_VERSION = "1.0.0"
_DEFAULT_PORT = 8080
_DEFAULT_CTX_SIZE = 4096
_DEFAULT_MODELS_DIR = "models"
_HEALTH_ENDPOINT = "/health"
_COMPLETION_ENDPOINT = "/v1/chat/completions"
_POLL_INTERVAL_S = 0.5
_START_TIMEOUT_S = 30


class LocalEngineError(Exception):
    pass


class EngineNotRunningError(LocalEngineError):
    pass


class EngineTimeoutError(LocalEngineError):
    pass


class EngineStartError(LocalEngineError):
    pass


class LocalEngine:
    def __init__(self, model_path=None, port=8080, ctx_size=4096, host="127.0.0.1", extra_args=None):
        self._port = port
        self._ctx_size = ctx_size
        self._host = host
        self._extra_args = extra_args or []
        self._model_path = self._resolve_model(model_path)
        self._process = None
        self._base_url = f"http://{host}:{port}"

    def _resolve_model(self, model_path):
        if model_path:
            p = Path(model_path)
            if p.exists():
                return p.resolve()
        env_path = os.environ.get("HUND_LOCAL_MODEL_PATH")
        if env_path:
            p = Path(env_path)
            if p.exists():
                return p.resolve()
        for candidate in [Path.cwd() / _DEFAULT_MODELS_DIR,
                          Path(__file__).resolve().parent.parent.parent / _DEFAULT_MODELS_DIR]:
            if candidate.exists():
                ggufs = sorted(candidate.glob("*.gguf"))
                if ggufs:
                    return ggufs[0].resolve()
        return None

    def _find_llama_server(self):
        exe = shutil.which("llama-server")
        if exe:
            return exe
        for candidate in [Path.cwd() / "llama-server", Path.cwd() / "llama-server.exe",
                          Path(__file__).resolve().parent.parent.parent / "llama-server",
                          Path(__file__).resolve().parent.parent.parent / "llama-server.exe"]:
            if candidate.exists():
                return str(candidate)
        return None

    def start(self):
        if self._process is not None:
            return {"status": "already_running", "port": self._port, "pid": self._process.pid}
        if self._model_path is None:
            raise EngineStartError("No GGUF model found. Set HUND_LOCAL_MODEL_PATH or place .gguf in ./models/")
        llama_server = self._find_llama_server()
        if llama_server is None:
            raise EngineStartError("llama-server not found in PATH. Install llama.cpp.")
        cmd = [llama_server, "--model", str(self._model_path), "--port", str(self._port),
               "--host", self._host, "--ctx-size", str(self._ctx_size), "--n-gpu-layers", "0"]
        cmd.extend(self._extra_args)
        try:
            self._process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except FileNotFoundError as exc:
            raise EngineStartError(f"Failed to start llama-server: {exc}") from exc
        start_time = time.time()
        while time.time() - start_time < _START_TIMEOUT_S:
            try:
                health = self._http_get(_HEALTH_ENDPOINT)
                if health is not None:
                    return {"status": "running", "port": self._port, "model": str(self._model_path), "pid": self._process.pid}
            except Exception:
                pass
            time.sleep(_POLL_INTERVAL_S)
        self.stop()
        raise EngineStartError(f"llama-server did not become ready within {_START_TIMEOUT_S}s on port {self._port}")

    def stop(self):
        if self._process is None:
            return {"status": "not_running"}
        try:
            self._process.terminate() if os.name == "nt" else self._process.send_signal(signal.SIGTERM)
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
        except Exception:
            pass
        self._process = None
        return {"status": "stopped"}

    def health(self):
        if self._process is None:
            raise EngineNotRunningError("Local engine is not running")
        data = self._http_get(_HEALTH_ENDPOINT)
        if data is None:
            raise EngineNotRunningError("Local engine health check failed")
        return {"running": True, "model": str(self._model_path) if self._model_path else "unknown",
                "port": self._port, "llama_version": data.get("version", "unknown"), "engine_version": LOCAL_ENGINE_VERSION}

    def complete(self, messages, temperature=0.7, max_tokens=2048, timeout=120):
        if self._process is None:
            raise EngineNotRunningError("Local engine is not running")
        body = json.dumps({"messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": False}).encode("utf-8")
        try:
            req = urllib.request.Request(f"{self._base_url}{_COMPLETION_ENDPOINT}", data=body,
                                          headers={"Content-Type": "application/json"}, method="POST")
            resp = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise LocalEngineError(f"Engine returned {exc.code}: {exc.read().decode()}") from exc
        except urllib.error.URLError as exc:
            raise EngineNotRunningError(f"Cannot reach engine: {exc.reason}") from exc
        except TimeoutError as exc:
            raise EngineTimeoutError(f"Request timed out after {timeout}s") from exc
        choice = resp.get("choices", [{}])[0]
        msg = choice.get("message", {})
        usage = resp.get("usage", {})
        return {"text": msg.get("content", ""), "finish_reason": choice.get("finish_reason", "stop"),
                "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0)}

    @property
    def is_running(self):
        return self._process is not None and self._process.poll() is None

    @property
    def port(self):
        return self._port

    @property
    def model_path(self):
        return self._model_path

    def _http_get(self, path):
        try:
            req = urllib.request.Request(f"{self._base_url}{path}")
            return json.loads(urllib.request.urlopen(req, timeout=5).read().decode("utf-8"))
        except Exception:
            return None
