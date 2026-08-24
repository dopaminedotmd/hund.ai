"""Stats Epochs — non-destructive progression resets and telemetry windowing."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..paths import db_path as default_db_path
from ..store.sqlite import connect

STATS_META_TABLE = "stats_meta"


def _ensure_stats_meta_table(db_path: Path | str | None = None) -> None:
    conn = connect(db_path)
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {STATS_META_TABLE} (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def get_current_epoch(db_path: Path | str | None = None) -> tuple[int, str]:
    """Get current stats epoch number and start timestamp.

    Returns (epoch_num, epoch_started_at).
    """
    _ensure_stats_meta_table(db_path)
    conn = connect(db_path)

    row_epoch = conn.execute(
        f"SELECT value FROM {STATS_META_TABLE} WHERE key='stats_epoch'"
    ).fetchone()
    row_started = conn.execute(
        f"SELECT value FROM {STATS_META_TABLE} WHERE key='epoch_started_at'"
    ).fetchone()

    conn.close()

    if not row_epoch or not row_started:
        # Initialize epoch 1
        now = "1970-01-01T00:00:00+00:00"
        set_epoch(1, now, db_path=db_path)
        return 1, now

    return int(row_epoch[0]), row_started[0]


def set_epoch(
    epoch: int,
    started_at: Optional[str] = None,
    db_path: Path | str | None = None,
) -> None:
    """Set specific epoch number and start timestamp."""
    _ensure_stats_meta_table(db_path)
    start_ts = started_at or datetime.now(timezone.utc).isoformat()
    conn = connect(db_path)

    conn.execute(
        f"""INSERT OR REPLACE INTO {STATS_META_TABLE} (key, value)
            VALUES ('stats_epoch', ?)""",
        (str(epoch),),
    )
    conn.execute(
        f"""INSERT OR REPLACE INTO {STATS_META_TABLE} (key, value)
            VALUES ('epoch_started_at', ?)""",
        (start_ts,),
    )
    conn.commit()
    conn.close()


def advance_epoch(db_path: Path | str | None = None) -> tuple[int, str]:
    """Advance to next epoch with current timestamp. Resets stats windows without deleting logs."""
    current_epoch, _ = get_current_epoch(db_path)
    new_epoch = current_epoch + 1
    now = datetime.now(timezone.utc).isoformat()
    set_epoch(new_epoch, now, db_path=db_path)
    return new_epoch, now
