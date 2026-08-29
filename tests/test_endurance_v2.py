from pathlib import Path
import sqlite3
import pytest

from hund.stats.base_stats import compute_endurance
from hund.stats.epochs import advance_epoch, get_current_epoch, set_epoch


def test_endurance_insufficient_samples_shows_collecting_evidence(tmp_path):
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    sess_dir = home / "sessions"
    sess_dir.mkdir(parents=True, exist_ok=True)
    db_file = sess_dir / "sessions.db"

    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE messages (id TEXT, session_id TEXT, role TEXT, content TEXT, tool_calls TEXT, rowid INTEGER PRIMARY KEY AUTOINCREMENT)")
    # Only 1 session with 4 messages
    for i in range(4):
        role = "user" if i % 2 == 0 else "assistant"
        conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES (?, 's1', ?, 'test')", (f"m{i}", role))
    conn.commit()
    conn.close()

    stat = compute_endurance(home=home, min_sample_threshold=3)
    assert stat["value"] is None
    assert stat.get("status_text") == "Collecting evidence"


def test_endurance_computes_rate_with_sufficient_sustained_samples(tmp_path):
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    sess_dir = home / "sessions"
    sess_dir.mkdir(parents=True, exist_ok=True)
    db_file = sess_dir / "sessions.db"

    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE messages (id TEXT, session_id TEXT, role TEXT, content TEXT, tool_calls TEXT, rowid INTEGER PRIMARY KEY AUTOINCREMENT)")
    # Insert 4 distinct sessions, each with 4 messages (sustained)
    for s_idx in range(4):
        sid = f"sess_{s_idx}"
        for m_idx in range(4):
            role = "user" if m_idx % 2 == 0 else "assistant"
            conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES (?, ?, ?, 'msg')", (f"m_{s_idx}_{m_idx}", sid, role))
    conn.commit()
    conn.close()

    stat = compute_endurance(home=home, min_sample_threshold=3)
    assert stat["value"] is not None
    assert stat["value"] == 100.0
    assert stat.get("sample_count") == 4
