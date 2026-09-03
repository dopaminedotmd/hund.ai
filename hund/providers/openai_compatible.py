"""OpenAI-compatible provider — funkar för DeepSeek, OpenAI, OpenRouter, Z.AI.

Verifierade endpoints (2026-06):
  DeepSeek: https://api.deepseek.com          modell: deepseek-chat
  Z.AI:     https://api.z.ai/api/paas/v4       modell: glm-4.6
Säkerhet: api_key hämtas från env/nyckelring, loggas ALDRIG.
"""
from __future__ import annotations

import json
import os
import re
import time

import httpx

from .base import CompletionResult, Message, ProviderClient

# Modeller beror på provider. Verifiera mot respektive /models-endpoint.

_PROTOCOL_BLOCK_PATTERNS = [
    re.compile(r"<[｜|│]\s*tool[_\s]*calls?[_\s]*begin\s*[｜|│]>.*?<[｜|│]\s*tool[_\s]*calls?[_\s]*end\s*[｜|│]>", re.DOTALL | re.IGNORECASE),
    re.compile(r"＜[｜|│]\s*tool[_\s]*calls?[_\s]*begin\s*[｜|│]＞.*?＜[｜|│]\s*tool[_\s]*calls?[_\s]*end\s*[｜|│]＞", re.DOTALL | re.IGNORECASE),
    re.compile(r"<\s*tool_call\s*>.*?<\s*/\s*tool_call\s*>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<\s*DSMLtool_calls?\s*>.*?<\s*/\s*DSMLtool_calls?\s*>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<\s*DSMLinvoke(?:\s+name=[^>]*)?>.*?<\s*/\s*DSMLinvoke\s*>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<\s*DSMLinvoke(?:\s+name=[^>]*)?\s*/>", re.DOTALL | re.IGNORECASE),
    re.compile(r"\[\s*TOOL_CALLS?\s*\].*?\[\s*/\s*TOOL_CALLS?\s*\]", re.DOTALL | re.IGNORECASE),
    re.compile(r"<\s*invoke\s+name=[^>]*>.*?<\s*/\s*invoke\s*>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<\s*function_call\s*>.*?<\s*/\s*function_call\s*>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<\|im_start\|>\s*tool.*?<\|im_end\|>", re.DOTALL | re.IGNORECASE),
]

_DANGLING_MARKER_PATTERNS = [
    re.compile(r"<[｜|│]\s*tool[_\s]*(?:calls?[_\s]*begin|calls?[_\s]*end|sep)\s*[｜|│]>", re.IGNORECASE),
    re.compile(r"＜[｜|│]\s*tool[_\s]*(?:calls?[_\s]*begin|calls?[_\s]*end|sep)\s*[｜|│]＞", re.IGNORECASE),
    re.compile(r"<\s*/?\s*tool_call\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*DSMLtool_calls?\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*DSMLinvoke(?:\s+name=[^>]*)?\s*/?>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*DSML[a-zA-Z0-9_]*\s*>", re.IGNORECASE),
    re.compile(r"\[\s*/?\s*TOOL_CALLS?\s*\]", re.IGNORECASE),
    re.compile(r"<\s*/?\s*invoke(?:\s+name=[^>]*)?>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*function_call\s*>", re.IGNORECASE),
]

_START_MARKER_PAT = re.compile(
    r"(?:<[｜|│]\s*tool[_\s]*calls?[_\s]*begin\s*[｜|│]>|"
    r"＜[｜|│]\s*tool[_\s]*calls?[_\s]*begin\s*[｜|│]＞|"
    r"<\s*tool_call\s*>|"
    r"<\s*DSMLtool_calls?\s*>|"
    r"<\s*DSMLinvoke(?:\s+name=[^>]*)?>|"
    r"<\s*DSML[a-zA-Z0-9_]*|"
    r"\[\s*TOOL_CALLS?\s*\]|"
    r"<\s*invoke\s+name=[^>]*>|"
    r"<\s*function_call\s*>|"
    r"<\|im_start\|>\s*tool)",
    re.IGNORECASE,
)

_END_MARKER_PAT = re.compile(
    r"(?:<[｜|│]\s*tool[_\s]*calls?[_\s]*end\s*[｜|│]>|"
    r"＜[｜|│]\s*tool[_\s]*calls?[_\s]*end\s*[｜|│]＞|"
    r"<\s*/\s*tool_call\s*>|"
    r"<\s*/\s*DSMLtool_calls?\s*>|"
    r"<\s*/\s*DSMLinvoke\s*>|"
    r"<\s*/\s*DSML[a-zA-Z0-9_]*\s*>|"
    r"\[\s*/\s*TOOL_CALLS?\s*\]|"
    r"<\s*/\s*invoke\s*>|"
    r"<\s*/\s*function_call\s*>|"
    r"<\|im_end\|>)",
    re.IGNORECASE,
)

_POTENTIAL_PREFIX_STARTERS = ("<", "＜", "[", "\u3008", "\uff1c")
_KNOWN_PREFIXES = (
    "<|", "<｜", "<tool", "<invoke", "<function", "<t", "<i", "<f",
    "<d", "<D", "<dsml", "<DSML", "<dsmltool", "<dsmlinvoke",
    "＜|", "＜｜", "＜tool", "＜t",
    "[t", "[T", "[tool", "[TOOL",
)


def strip_unbalanced_raw_markers(text: str) -> str:
    """Repair or strip raw unbalanced '**' markers in Swedish and English prose."""
    if "**" not in text:
        return text
    text = re.sub(r"^\*\*U([A-ZÅÄÖa-zåäö])", r"\1", text)
    text = re.sub(r"\*\*U\b", "", text)
    count = text.count("**")
    if count % 2 != 0:
        if text.startswith("**") and not text.startswith("****"):
            text = text[2:]
        elif text.endswith("**") and not text.endswith("****"):
            text = text[:-2]
        else:
            parts = text.rsplit("**", 1)
            text = "".join(parts)
    text = re.sub(r"(?<=\s)\*\*(?=\s|$)", "", text)
    text = re.sub(r"(?<=^)\*\*(?=\s)", "", text)
    return text


def filter_leaked_protocol(text: str) -> str:
    """Filter known DSML and function-calling protocol markers and malformed blocks from model output."""
    if not text:
        return text
    cleaned = text
    for pat in _PROTOCOL_BLOCK_PATTERNS:
        cleaned = pat.sub("", cleaned)
    for pat in _DANGLING_MARKER_PATTERNS:
        cleaned = pat.sub("", cleaned)
    cleaned = strip_unbalanced_raw_markers(cleaned)
    return cleaned


class StreamProtocolFilter:
    """Bounded streaming protocol sanitizer that prevents leaked DSML markup from appearing in chat."""

    def __init__(self, max_prefix_len: int = 48) -> None:
        self._buffer = ""
        self._in_block = False
        self._max_prefix_len = max_prefix_len

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        self._buffer += chunk
        emitted_parts: list[str] = []

        while self._buffer:
            if not self._in_block:
                # Look for a complete start marker
                start_m = _START_MARKER_PAT.search(self._buffer)
                if start_m:
                    start_idx = start_m.start()
                    # Emit confirmed safe text before the start marker
                    if start_idx > 0:
                        emitted_parts.append(filter_leaked_protocol(self._buffer[:start_idx]))
                    self._buffer = self._buffer[start_m.end():]
                    self._in_block = True
                    continue

                # Check if buffer ends with a potential marker prefix
                last_starter = -1
                for starter in _POTENTIAL_PREFIX_STARTERS:
                    pos = self._buffer.rfind(starter)
                    if pos > last_starter and (len(self._buffer) - pos) <= self._max_prefix_len:
                        candidate = self._buffer[pos:].lower()
                        if any(candidate.startswith(p.lower()) or p.lower().startswith(candidate) for p in _KNOWN_PREFIXES):
                            last_starter = pos

                if last_starter != -1:
                    # Hold the potential prefix in buffer, emit safe prefix
                    safe_chunk = self._buffer[:last_starter]
                    if safe_chunk:
                        emitted_parts.append(filter_leaked_protocol(safe_chunk))
                    self._buffer = self._buffer[last_starter:]
                    break
                else:
                    # Entire buffer is safe
                    emitted_parts.append(filter_leaked_protocol(self._buffer))
                    self._buffer = ""
                    break
            else:
                # We are inside a protocol block, look for end marker
                end_m = _END_MARKER_PAT.search(self._buffer)
                if end_m:
                    # Discard everything up to end marker
                    self._buffer = self._buffer[end_m.end():]
                    self._in_block = False
                    continue
                else:
                    # Still in protocol block, wait for end marker
                    if len(self._buffer) > 10000:
                        self._buffer = self._buffer[-200:]
                    break

        return "".join(emitted_parts)

    def flush(self) -> str:
        if self._in_block:
            self._buffer = ""
            return ""
        out = filter_leaked_protocol(self._buffer)
        self._buffer = ""
        return out


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
        self, messages, tools, model, stream: bool, max_tokens: int | None = None
    ) -> dict:
        payload: dict = {
            "model": model or self.default_model,
            "messages": [_msg_to_dict(m) for m in messages],
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
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
        max_tokens: int | None = None,
    ) -> CompletionResult:
        """Icke-streamande. För live-output, se stream()."""
        self._require_key()
        url = f"{self.base_url}/chat/completions"
        t0 = time.perf_counter()
        timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=self._payload(messages, tools, model, False, max_tokens), headers=self._headers())
                latency_ms = int((time.perf_counter() - t0) * 1000)
                if resp.status_code >= 400:
                    raise RuntimeError(self._err_msg(resp))
                data = resp.json()
        except httpx.TimeoutException as e:
            raise RuntimeError(f"provider request timeout: {e}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"provider HTTP error: {e}") from e
        choice = data["choices"][0]
        msg = choice.get("message", {})
        usage = data.get("usage", {}) or {}
        raw_text = msg.get("content") or ""
        reasoning_text = msg.get("reasoning_content") or msg.get("reasoning") or ""
        filtered_text = filter_leaked_protocol(raw_text)
        self.last_result = CompletionResult(
            text=filtered_text,
            tool_calls=msg.get("tool_calls") or [],
            finish_reason=choice.get("finish_reason", "stop"),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            latency_ms=latency_ms,
            raw=data,
            reasoning_content=reasoning_text,
        )
        if reasoning_text:
            try:
                from ..store.sqlite import log_request_reasoning
                log_request_reasoning(reasoning_text, run_id=getattr(self, "current_run_id", None))
            except Exception:
                pass
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
        reasoning_acc: list[str] = []
        finish = "stop"
        pt = ct = tt = 0
        t0 = time.perf_counter()
        protocol_filter = StreamProtocolFilter()

        timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
        try:
            with httpx.Client(timeout=timeout) as client:
                with client.stream(
                    "POST",
                    url,
                    json=self._payload(messages, tools, model, True),
                    headers=self._headers(),
                ) as resp:
                    if resp.status_code >= 400:
                        body = resp.read().decode("utf-8", "replace")
                        raise RuntimeError(f"Provider HTTP {resp.status_code} — {body[:200]}")
                    deadline = time.monotonic() + self.timeout
                    for line in resp.iter_lines():
                        if time.monotonic() > deadline:
                            raise RuntimeError(f"provider stream timeout after {self.timeout:.0f}s")
                        deadline = time.monotonic() + self.timeout
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
                            r_piece = delta.get("reasoning_content") or delta.get("reasoning")
                            if r_piece:
                                reasoning_acc.append(r_piece)
                            if delta.get("content"):
                                filtered_chunk = protocol_filter.feed(delta["content"])
                                if filtered_chunk:
                                    yield filtered_chunk
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
                    final_chunk = protocol_filter.flush()
                    if final_chunk:
                        yield final_chunk
        except httpx.TimeoutException as e:
            raise RuntimeError(f"provider stream timeout: {e}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"provider HTTP error: {e}") from e

        reasoning_str = "".join(reasoning_acc)
        self.last_result = CompletionResult(
            text="",
            tool_calls=[tool_acc[i] for i in sorted(tool_acc)],
            finish_reason=finish,
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=tt,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            reasoning_content=reasoning_str,
        )
        if reasoning_str:
            try:
                from ..store.sqlite import log_request_reasoning
                log_request_reasoning(reasoning_str, run_id=getattr(self, "current_run_id", None))
            except Exception:
                pass
