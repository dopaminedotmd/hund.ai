"""Tests for SQLite WAL mode."""
import tempfile
from pathlib import Path
from hund.store.sqlite import _open


def test_sqlite_wal_mode_enabled():
    """Verifiera att PRAGMA journal_mode=WAL är aktiverat vid anslutning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        schema = "CREATE TABLE IF NOT EXISTS test (id TEXT PRIMARY KEY);"
        
        conn = _open(db_path, schema)
        try:
            cursor = conn.execute("PRAGMA journal_mode;")
            mode = cursor.fetchone()[0]
            # journal_mode kan vara 'wal' (eller 'memory' i vissa specifika fall om den inte sparas på disk,
            # men på disk ska den vara 'wal').
            assert mode.lower() == "wal"
        finally:
            conn.close()
