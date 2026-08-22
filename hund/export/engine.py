"""ExportEngine — dataset export from trace events to SFT/JSONL format.

Queries trace_events from SQLite, builds prompt-response pairs with
v2 redaction, and exports to standard fine-tuning formats.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..learning.redactor_v2 import redact_text_v2, RedactableConfig
from ..store.sqlite import connect
from .filters import Filter
from .manifest import ExportManifest

REDACTOR_VERSION = "v2.0.0"


class ExportError(Exception):
    """Base exception for export operations."""


@dataclass
class PromptResponsePair:
    """A single prompt-response pair for SFT/DPO training.

    All text fields are redacted via Redactor v2 before storage.
    """

    pair_id: str
    session_id: str
    run_id: str
    prompt: str  # user message + system prompt (redacted)
    response: str  # agent response + tool results (redacted)
    risk: str = "safe"
    blocked_fields: list[str] = field(default_factory=list)
    created_at: str = ""

    def to_jsonl_dict(self) -> dict[str, Any]:
        """JSONL format: simple prompt/response."""
        return {
            "pair_id": self.pair_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "prompt": self.prompt,
            "response": self.response,
            "risk": self.risk,
            "blocked_fields": self.blocked_fields,
            "created_at": self.created_at,
        }

    def to_sft_dict(self) -> dict[str, Any]:
        """SFT format: messages array (OpenAI-compatible)."""
        return {
            "pair_id": self.pair_id,
            "messages": [
                {"role": "user", "content": self.prompt},
                {"role": "assistant", "content": self.response},
            ],
        }


class ExportEngine:
    """Query trace events, build pairs, export to file.

    Usage::

        engine = ExportEngine(redaction_config=RedactableConfig())
        pairs = engine.build_pairs(filter_obj=Filter().with_limit(100))
        engine.export_to_jsonl(pairs, Path("export.jsonl"))
    """

    def __init__(
        self,
        redaction_config: RedactableConfig | None = None,
        db_path: Path | None = None,
    ) -> None:
        self._config = redaction_config or RedactableConfig()
        self._db_path = db_path

    def query_traces(self, filter_obj: Filter | None = None) -> list[dict[str, Any]]:
        """Query trace events with optional filters.

        Args:
            filter_obj: Filter instance. If None, returns recent 500 events.

        Returns:
            List of raw trace event dicts.
        """
        if filter_obj is None:
            filter_obj = Filter()

        where, params = filter_obj.build()
        limit = filter_obj.limit
        offset = filter_obj.offset

        conn = connect(self._db_path)
        columns = [col[1] for col in conn.execute("PRAGMA table_info(trace_events)").fetchall()]

        sql = f"SELECT * FROM trace_events{where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        conn.close()

        traces = []
        for row in rows:
            trace = dict(zip(columns, row))
            if "payload_redacted" in trace and trace["payload_redacted"]:
                try:
                    trace["payload_redacted"] = json.loads(trace["payload_redacted"])
                except (json.JSONDecodeError, TypeError):
                    pass
            traces.append(trace)

        return traces

    def build_pairs(self, filter_obj: Filter | None = None) -> list[PromptResponsePair]:
        """Build prompt-response pairs from trace events.

        Pairs system prompt + user message as prompt, and assistant response
        + tool results as response. All text is redacted via v2.

        Args:
            filter_obj: Filter for trace queries.

        Returns:
            List of PromptResponsePair.
        """
        traces = self.query_traces(filter_obj)
        pairs: list[PromptResponsePair] = []

        # Group traces by run_id for context
        runs: dict[str, list[dict[str, Any]]] = {}
        for t in traces:
            rid = t.get("run_id", "unknown")
            if rid not in runs:
                runs[rid] = []
            runs[rid].append(t)

        for run_id, events in runs.items():
            # Sort chronologically
            events.sort(key=lambda e: e.get("created_at", ""))

            # Build prompt from system + user events
            prompt_parts: list[str] = []
            response_parts: list[str] = []
            session_id = events[0].get("session_id", "unknown") if events else "unknown"

            for ev in events:
                event_type = ev.get("event_type", "")
                payload = ev.get("payload_redacted", {})

                if event_type in ("run_started", "turn_started", "context_compressed"):
                    if isinstance(payload, dict) and "compressed" not in event_type:
                        prompt_parts.append(str(payload.get("goal", "")))

                if event_type == "tool_call_completed":
                    tool_name = ev.get("tool_name", "unknown")
                    result = payload.get("result", "") if isinstance(payload, dict) else ""
                    response_parts.append(f"[Tool {tool_name}]: {result}")

                if event_type == "final_claim":
                    claim = payload.get("claim", "") if isinstance(payload, dict) else ""
                    if isinstance(claim, str):
                        response_parts.append(claim)

            prompt_text = "\n".join(p for p in prompt_parts if p)
            response_text = "\n".join(r for r in response_parts if r)

            if not prompt_text and not response_text:
                continue
            if not prompt_text:
                prompt_text = "(system context unavailable)"
            if not response_text:
                response_text = "(no agent response recorded)"

            # Redact via v2
            prompt_result = redact_text_v2(prompt_text, config=self._config)
            response_result = redact_text_v2(response_text, config=self._config)

            risk = "safe"
            all_blocked = list(set(prompt_result.blocked_fields + response_result.blocked_fields))
            if all_blocked:
                risk = "review_required"

            pair = PromptResponsePair(
                pair_id=str(uuid.uuid4()),
                session_id=session_id,
                run_id=run_id,
                prompt=prompt_result.text,
                response=response_result.text,
                risk=risk,
                blocked_fields=all_blocked,
                created_at=events[0].get("created_at", ""),
            )
            pairs.append(pair)

        return pairs

    def export_to_jsonl(
        self,
        pairs: list[PromptResponsePair],
        output_path: str | Path,
    ) -> Path:
        """Export pairs to JSONL format (one JSON object per line).

        Args:
            pairs: List of PromptResponsePair.
            output_path: Path to output file.

        Returns:
            Path to the exported file.

        Raises:
            ExportError: On write failure.
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(path, "w", encoding="utf-8") as f:
                for pair in pairs:
                    f.write(json.dumps(pair.to_jsonl_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            raise ExportError(f"Failed to write {path}: {exc}") from exc

        return path

    def export_to_sft(
        self,
        pairs: list[PromptResponsePair],
        output_path: str | Path,
    ) -> Path:
        """Export pairs to SFT format (messages array per line).

        Args:
            pairs: List of PromptResponsePair.
            output_path: Path to output file.

        Returns:
            Path to the exported file.
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(path, "w", encoding="utf-8") as f:
                for pair in pairs:
                    f.write(json.dumps(pair.to_sft_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            raise ExportError(f"Failed to write {path}: {exc}") from exc

        return path

    def dry_run(self, pairs: list[PromptResponsePair]) -> dict[str, Any]:
        """Generate statistics for a set of pairs without exporting.

        Args:
            pairs: List of PromptResponsePair.

        Returns:
            Dict with stats: pair_count, risk_counts, blocked_fields, avg_prompt_len, etc.
        """
        if not pairs:
            return {
                "pair_count": 0,
                "risk_counts": {},
                "blocked_fields": [],
                "avg_prompt_len": 0,
                "avg_response_len": 0,
                "total_chars": 0,
                "redactor_version": REDACTOR_VERSION,
            }

        risk_counts: dict[str, int] = {}
        all_blocked: set[str] = set()
        total_prompt_len = 0
        total_response_len = 0
        total_chars = 0

        for pair in pairs:
            risk_counts[pair.risk] = risk_counts.get(pair.risk, 0) + 1
            all_blocked.update(pair.blocked_fields)
            total_prompt_len += len(pair.prompt)
            total_response_len += len(pair.response)
            total_chars += len(pair.prompt) + len(pair.response)

        n = len(pairs)
        return {
            "pair_count": n,
            "risk_counts": risk_counts,
            "blocked_fields": sorted(all_blocked),
            "avg_prompt_len": total_prompt_len // n,
            "avg_response_len": total_response_len // n,
            "total_chars": total_chars,
            "redactor_version": REDACTOR_VERSION,
        }

    def save_manifest(
        self,
        pairs: list[PromptResponsePair],
        output_path: Path,
        filter_obj: Filter | None = None,
        export_format: str = "jsonl",
    ) -> ExportManifest:
        """Create and save an export manifest.

        Args:
            pairs: List of exported pairs.
            output_path: Path to the export file.
            filter_obj: Filters used for the export.
            export_format: Format identifier.

        Returns:
            ExportManifest instance.
        """
        manifest = ExportManifest(
            export_format=export_format,
            filter_obj=filter_obj or Filter(),
            pair_count=len(pairs),
            redactor_version=REDACTOR_VERSION,
            output_path=str(output_path.resolve()),
        )
        manifest.save(output_path)
        return manifest
