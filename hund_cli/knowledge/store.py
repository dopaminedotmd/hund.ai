"""Knowledge store — lokala kunskapsenheter med LFU/MRU-retrieval.

V1-relevance (review): frekvens + aktualitet, top-K. Ingen 9-term formel förrän
benchmark visar att den behövs. bump_usage vid användning = self-organizing.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ..store.sqlite import connect


def add(domain: str, trigger: str, rule: str, source: str = "manual") -> str:
    conn = connect()
    uid = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO knowledge_units
           (id, created_at, domain, trigger, rule, frequency, last_used,
            success_count, fail_count, source)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (uid, datetime.now(timezone.utc).isoformat(), domain, trigger, rule, 0, None, 0, 0, source),
    )
    conn.commit()
    conn.close()
    return uid


def list_units(domain: str | None = None) -> list[tuple]:
    conn = connect()
    if domain:
        rows = conn.execute(
            """SELECT substr(id,1,8), domain, trigger, rule, frequency, success_count
               FROM knowledge_units WHERE domain=? ORDER BY frequency DESC""",
            (domain,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT substr(id,1,8), domain, trigger, rule, frequency, success_count
               FROM knowledge_units ORDER BY frequency DESC"""
        ).fetchall()
    conn.close()
    return rows


def top_k(domain: str, k: int = 5) -> list[tuple]:
    """LFU/MRU hybrid: frekvens först, sen aktualitet. Top-K per domain."""
    conn = connect()
    rows = conn.execute(
        """SELECT trigger, rule FROM knowledge_units
           WHERE domain=? ORDER BY frequency DESC, last_used DESC LIMIT ?""",
        (domain, k),
    ).fetchall()
    conn.close()
    return rows


def bump_usage(uid_prefix: str, success: bool = True) -> int:
    conn = connect()
    now = datetime.now(timezone.utc).isoformat()
    col = "success_count" if success else "fail_count"
    cur = conn.execute(
        f"UPDATE knowledge_units SET frequency=frequency+1, {col}={col}+1, last_used=? WHERE id LIKE ?",
        (now, uid_prefix + "%"),
    )
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


def domains() -> list[str]:
    conn = connect()
    rows = conn.execute("SELECT DISTINCT domain FROM knowledge_units").fetchall()
    conn.close()
    return [r[0] for r in rows]
