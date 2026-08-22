"""ExportManifest — metadata for dataset exports."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .filters import Filter


class ExportManifest:
    """Metadata for a single dataset export.

    Serialized as JSON and stored alongside the export file.
    """

    def __init__(
        self,
        *,
        export_id: str | None = None,
        source: str = "trace_events",
        export_format: str = "jsonl",
        filter_obj: Filter | None = None,
        pair_count: int = 0,
        redactor_version: str = "v2.0.0",
        output_path: str = "",
    ) -> None:
        self.export_id = export_id or str(uuid.uuid4())
        self.exported_at = datetime.now(timezone.utc).isoformat()
        self.source = source
        self.export_format = export_format
        self.filter = filter_obj or Filter()
        self.pair_count = pair_count
        self.redactor_version = redactor_version
        self.output_path = output_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "export_id": self.export_id,
            "exported_at": self.exported_at,
            "source": self.source,
            "export_format": self.export_format,
            "filters": self.filter.to_dict(),
            "pair_count": self.pair_count,
            "redactor_version": self.redactor_version,
            "output_path": self.output_path,
        }

    def save(self, path: Path) -> Path:
        """Save manifest as JSON next to the export file."""
        manifest_path = path.with_suffix(".manifest.json")
        manifest_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return manifest_path

    @classmethod
    def load(cls, path: Path) -> ExportManifest:
        """Load manifest from JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        manifest = cls(
            export_id=data.get("export_id"),
            source=data.get("source", "trace_events"),
            export_format=data.get("export_format", "jsonl"),
            pair_count=data.get("pair_count", 0),
            redactor_version=data.get("redactor_version", "v2.0.0"),
            output_path=data.get("output_path", ""),
        )
        manifest.exported_at = data.get("exported_at", manifest.exported_at)
        filter_data = data.get("filters", {})
        if filter_data:
            manifest.filter = Filter(
                run_id=filter_data.get("run_id"),
                session_id=filter_data.get("session_id"),
                event_type=filter_data.get("event_type"),
                actor=filter_data.get("actor"),
                risk=filter_data.get("risk"),
                tool_name=filter_data.get("tool_name"),
                since=filter_data.get("since"),
                until=filter_data.get("until"),
                limit=filter_data.get("limit", 500),
                offset=filter_data.get("offset", 0),
            )
        return manifest
