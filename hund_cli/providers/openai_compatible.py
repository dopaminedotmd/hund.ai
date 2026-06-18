"""OpenAI-compatible provider — funkar för DeepSeek, OpenAI, OpenRouter, Z.AI.

Verifierade endpoints (2026-06):
  DeepSeek: https://api.deepseek.com          modell: deepseek-chat
  Z.AI:     https://api.z.ai/api/paas/v4       modell: glm-4.6
Säkerhet: api_key hämtas från env/nyckelring, loggas ALDRIG.
"""
from __future__ import annotations

import json
import os
import time

import httpx

from .base import CompletionResult, Message, ProviderClient

# Modeller beror på provider. Verifiera mot respektive /models-endpoint.


def _msg_to_dict(m: Message) -> dict:
    """Serialisera inkl. tool_calls / tool-role för OpenAI-compatible API."""
    d: dict = {"role": m.role, "content": m.content}
    if m.tool_calls:
        d["tool_calls"] = m.tool_calls
    if m.tool_call_id:
        d["tool_call_id"] = m.tool_call_id
    return d


class OpenAICompatibleClient(ProviderClient):
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        default_model: str,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("HUND_API_KEY", "")
        self.default_model = default_model
        self.timeout = timeout
        self.last_result: CompletionResult | None = None  # sätts av stream()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",  # loggas ej av oss
            "Content-Type": "application/json",
        }

    def _require_key(self) -> None:
        if not self.api_key:
            raise RuntimeError("Ingen API-nyckel. Sätt HUND_API_KEY i env.")

    def _payload(
        self, messages, tools, model, stream: bool
    ) -> dict:
        payload: dict = {
            "model": model or self.default_model,
            "messages": [_msg_to_dict(m) for m in messages],
        }
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return payload

    def complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> CompletionResult:
        """Icke-streamande. För live-output, se stream()."""
        self._require_key()
        url = f"{self.base_url}/chat/completions"
        t0 = time.perf_counter()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=self._payload(messages, tools, model, False), headers=self._headers())
            latency_ms = int((time.perf_counter() - t0) * 1000)
            if resp.status_code >= 400:
                raise RuntimeError(self._err_msg(resp))
            data = resp.json()
        choice = data["choices"][0]
        msg = choice.get("message", {})
        usage = data.get("usage", {}) or {}
        self.last_result = CompletionResult(
            text=msg.get("content") or "",
            tool_calls=msg.get("tool_calls") or [],
            finish_reason=choice.get("finish_reason", "stop"),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            latency_ms=latency_ms,
            raw=data,
        )
        return self.last_result

    @staticmethod
    def _err_msg(resp) -> str:
        try:
            err = resp.json().get("error", {})
            return f"Provider HTTP {resp.status_code} — {err.get('code','?')}: {err.get('message', resp.text)}"
        except Exception:
            return f"Provider HTTP {resp.status_code} — {resp.text[:200]}"

    def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        model: str | None = None,
    ):
        """Streaming generator: yieldar text-chunks live.

        Sätter self.last_result när strömmen stängs (text='', tool_calls=[...],
        usage insamlat). Används för både live-print och tool-loop.
        """
        self._require_key()
        url = f"{self.base_url}/chat/completions"
        tool_acc: dict[int, dict] = {}
        finish = "stop"
        pt = ct = tt = 0
        t0 = time.perf_counter()

        with httpx.Client(timeout=self.timeout) as client:
            with client.stream(
                "POST",
                url,
                json=self._payload(messages, tools, model, True),
                headers=self._headers(),
            ) as resp:
                if resp.status_code >= 400:
                    body = resp.read().decode("utf-8", "replace")
                    raise RuntimeError(f"Provider HTTP {resp.status_code} — {body[:200]}")
                for line in resp.iter_lines():
                    if not line or line.startswith(":"):  # keepalive-kommentar
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta", {}) or {}
                        if delta.get("content"):
                            yield delta["content"]
                        for tc in delta.get("tool_calls") or []:
                            idx = tc.get("index", 0)
                            acc = tool_acc.setdefault(
                                idx,
                                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                            )
                            if tc.get("id"):
                                acc["id"] = tc["id"]
                            fn = tc.get("function", {}) or {}
                            if fn.get("name"):
                                acc["function"]["name"] += fn["name"]
                            if fn.get("arguments") is not None:
                                acc["function"]["arguments"] += fn["arguments"]
                        if choices[0].get("finish_reason"):
                            finish = choices[0]["finish_reason"]
                    u = chunk.get("usage")
                    if u:
                        pt, ct, tt = u.get("prompt_tokens", 0), u.get("completion_tokens", 0), u.get("total_tokens", 0)

        self.last_result = CompletionResult(
            text="",
            tool_calls=[tool_acc[i] for i in sorted(tool_acc)],
            finish_reason=finish,
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=tt,
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
