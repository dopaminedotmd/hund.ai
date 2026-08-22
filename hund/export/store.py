"""ExportStore — log export operations in SQLite."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..store.sqlite import connect


def log_export(
    export_format: str,
    pair_count: int,
    output_path: str,
    filters_json: str = "{}",
    redactor_version: str = "v2.0.0",
    db_path: Path | None = None,
) -> str:
    """Log an export operation to export_log table.

    Returns:
        export_id.
    """
    export_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    conn = connect(db_path)
    conn.execute(
        """INSERT INTO export_log (export_id, created_at, export_format, pair_count, output_path, filters_json, redactor_version)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (export_id, created_at, export_format, pair_count, output_path, filters_json, redactor_version),
    )
    conn.commit()
    conn.close()
    return export_id


def list_exports(limit: int = 20, db_path: Path | None = None) -> list[dict[str, Any]]:
    """List recent export log entries."""
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT export_id, created_at, export_format, pair_count, output_path, filters_json, redactor_version "
        "FROM export_log ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()

    exports = []
    for row in rows:
        exports.append({
            "export_id": row[0],
            "created_at": row[1],
            "export_format": row[2],
            "pair_count": row[3],
            "output_path": row[4],
            "filters_json": row[5],
            "redactor_version": row[6],
        })
    return exports
