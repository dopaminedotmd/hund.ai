"""Sessions — sessionsarkiv + fulltext-sök (FTS5).

Varje meddelande sparas under HundHome/sessions/sessions.db. Vid `hund`-start kan
senaste aktiva session återupptas (se agent/loop.run_repl). REPL-slash + CLI söker
fulltext via FTS5.

FTS-strategi: `messages_fts` är en fristående FTS5-tabell (inte external content).
session_id + msg_id lagras UNINDEXED → sökbara tillbaka till rätt session utan
triggers. Enkelt och robust för lokal enkeltrådad CLI.

`home`-param tillåter testisolation (tmp-HundHome), samma mönster som knowledge/memory.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    title TEXT DEFAULT '',
    active INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,                 -- user|assistant|system|tool
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    seq INTEGER NOT NULL,
    run_id TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    session_id UNINDEXED,
    msg_id UNINDEXED
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _home() -> Path:
    from ..paths import hund_home

    return hund_home()


def _connect(home: Optional[Path] = None) -> sqlite3.Connection:
    base = home if home is not None else _home()
    db = base / "sessions" / "sessions.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate_sessions(conn)
    return conn


def _migrate_sessions(conn: sqlite3.Connection) -> None:
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(messages)")
    }
    if "run_id" not in existing:
        conn.execute("ALTER TABLE messages ADD COLUMN run_id TEXT")
        conn.commit()


def _match_prefix(session_id: str) -> tuple[str, str]:
    """Matcha exakt id ELLER prefix. Returnera (sql_fragment-villkor ej — används per call)."""
    return (session_id, session_id + "%")


def create(title: str = "", home: Optional[Path] = None) -> str:
    """Ny session, markera aktiv (deaktiverar övriga). Returnera fullt id."""
    sid = uuid.uuid4().hex
    conn = _connect(home)
    conn.execute("UPDATE sessions SET active=0")
    conn.execute(
        "INSERT INTO sessions(id, created_at, title, active, message_count) "
        "VALUES(?,?,?,?,0)",
        (sid, _now(), title, 1),
    )
    conn.commit()
    conn.close()
    return sid


def set_active(session_id: str, home: Optional[Path] = None) -> int:
    """Aktivera session (exakt id eller prefix). Returnera antal updaterade rader."""
    conn = _connect(home)
    conn.execute("UPDATE sessions SET active=0")
    exact, prefix = _match_prefix(session_id)
    n = conn.execute(
        "UPDATE sessions SET active=1 WHERE id=? OR id LIKE ?", (exact, prefix)
    ).rowcount
    conn.commit()
    conn.close()
    return n


def get_active(home: Optional[Path] = None) -> Optional[dict]:
    conn = _connect(home)
    row = conn.execute(
        "SELECT id, created_at, title, message_count FROM sessions WHERE active=1"
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "created_at": row[1], "title": row[2], "message_count": row[3]}


def _resolve(session_id: str, conn: sqlite3.Connection) -> Optional[str]:
    """Lös prefix → fullt id."""
    exact, prefix = _match_prefix(session_id)
    row = conn.execute(
        "SELECT id FROM sessions WHERE id=? OR id LIKE ? ORDER BY active DESC LIMIT 1",
        (exact, prefix),
    ).fetchone()
    return row[0] if row else None


def add_message(
    session_id: str, role: str, content: str, home: Optional[Path] = None, run_id: Optional[str] = None
) -> str:
    """Spara ett meddelande (+ FTS-rad). Sätter title från första user-meddelandet."""
    now = _now()
    mid = uuid.uuid4().hex
    conn = _connect(home)
    seq = conn.execute(
        "SELECT COALESCE(MAX(seq),0)+1 FROM messages WHERE session_id=?", (session_id,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO messages(id, session_id, role, content, created_at, seq, run_id) "
        "VALUES(?,?,?,?,?,?,?)",
        (mid, session_id, role, content, now, seq, run_id),
    )
    conn.execute(
        "INSERT INTO messages_fts(content, session_id, msg_id) VALUES(?,?,?)",
        (content, session_id, mid),
    )
    conn.execute("UPDATE sessions SET message_count=message_count+1 WHERE id=?", (session_id,))
    if role == "user":
        row = conn.execute("SELECT title FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row and not row[0]:
            conn.execute(
                "UPDATE sessions SET title=? WHERE id=?",
                (content[:60].replace("\n", " ").strip(), session_id),
            )
    conn.commit()
    conn.close()
    return mid


def list_messages(session_id: str, home: Optional[Path] = None) -> list[tuple]:
    """Alla meddelanden i seq-ordning: [(role, content), ...]."""
    conn = _connect(home)
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id=? ORDER BY seq",
        (session_id,),
    ).fetchall()
    conn.close()
    return rows


def messages_for_run(
    session_id: str, run_id: str, home: Optional[Path] = None
) -> list[tuple[str, str]]:
    """Read one completed run without reconstructing or mutating the session."""
    conn = _connect(home)
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id=? AND run_id=? ORDER BY seq",
        (session_id, run_id),
    ).fetchall()
    conn.close()
    return rows


def history(session_id: str, home: Optional[Path] = None) -> list[tuple]:
    """Endast user+assistant (resume-kontext). Skippar system/tool för säker rekonstruktion."""
    conn = _connect(home)
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id=? "
        "AND role IN ('user','assistant') ORDER BY seq",
        (session_id,),
    ).fetchall()
    conn.close()
    return rows


def list_sessions(limit: int = 10, home: Optional[Path] = None) -> list[tuple]:
    """[(id, created_at, title, message_count, active), ...] nyast först."""
    conn = _connect(home)
    rows = conn.execute(
        "SELECT id, created_at, title, message_count, active "
        "FROM sessions ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def info(session_id: str, home: Optional[Path] = None) -> Optional[dict]:
    conn = _connect(home)
    full = _resolve(session_id, conn)
    if not full:
        conn.close()
        return None
    row = conn.execute(
        "SELECT id, created_at, title, active, message_count FROM sessions WHERE id=?",
        (full,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "created_at": row[1],
        "title": row[2],
        "active": bool(row[3]),
        "message_count": row[4],
    }


def search(q: str, home: Optional[Path] = None, limit: int = 50) -> list[tuple]:
    """FTS5 fulltext. Returnerar [(session_id, role, snippet, created_at), ...]."""
    if not q.strip():
        return []
    # FTS5: citera termen, dubbla inre citattecken för att escapa.
    fts_q = '"' + q.replace('"', '""') + '"'
    conn = _connect(home)
    rows = conn.execute(
        "SELECT m.session_id, m.role, snippet(messages_fts,0,'[',']','…',12), m.created_at "
        "FROM messages_fts f JOIN messages m ON m.id=f.msg_id "
        "WHERE messages_fts MATCH ? ORDER BY m.created_at DESC LIMIT ?",
        (fts_q, limit),
    ).fetchall()
    conn.close()
    return rows


def delete(session_id: str, home: Optional[Path] = None) -> int:
    """Radera session + meddelanden + FTS-rader. Returnera antal raderade sessioner."""
    conn = _connect(home)
    full = _resolve(session_id, conn)
    if not full:
        conn.close()
        return 0
    conn.execute("DELETE FROM messages_fts WHERE session_id=?", (full,))
    conn.execute("DELETE FROM messages WHERE session_id=?", (full,))
    n = conn.execute("DELETE FROM sessions WHERE id=?", (full,)).rowcount
    conn.commit()
    conn.close()
    return n
