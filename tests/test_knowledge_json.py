"""Fas 9.5 Del C — knowledge JSON-store + migrering.

Verifierar: per-domän JSON, LFU/MRU top-K, bump_usage, list_units,
persistens över omläsning, och v1→v2-migrering från SQLite.
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from hund_cli.knowledge import migrate
from hund_cli.knowledge import store as kstore


def test_add_writes_domain_json(tmp_path):
    dom = f"dom_{uuid.uuid4().hex}"
    uid = kstore.add(dom, "trig", "regel", home=tmp_path)
    f = tmp_path / "brain" / "knowledge" / f"{dom}.json"
    assert f.exists()
    import json

    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["domain"] == dom
    assert data["units"][0]["id"] == uid
    assert data["units"][0]["frequency"] == 0


def test_top_k_lfu_order(tmp_path):
    dom = f"lfu_{uuid.uuid4().hex}"
    a = kstore.add(dom, "ta", "ra", home=tmp_path)
    kstore.add(dom, "tb", "rb", home=tmp_path)
    kstore.bump_usage(a, home=tmp_path)
    kstore.bump_usage(a, home=tmp_path)
    top = kstore.top_k(dom, k=5, home=tmp_path)
    assert top[0] == ("ta", "ra")  # mest frekvent först


def test_bump_usage_updates_counts(tmp_path):
    dom = f"bump_{uuid.uuid4().hex}"
    uid = kstore.add(dom, "t", "r", home=tmp_path)
    n = kstore.bump_usage(uid, success=True, home=tmp_path)
    assert n == 1
    rows = kstore.list_units(dom, home=tmp_path)
    assert rows[0][4] == 1  # frequency
    assert rows[0][5] == 1  # success_count


def test_persistence_across_reload(tmp_path):
    dom = f"pers_{uuid.uuid4().hex}"
    kstore.add(dom, "t", "r", home=tmp_path)
    # Ny "session" läser samma fil
    top = kstore.top_k(dom, home=tmp_path)
    assert top == [("t", "r")]


def test_domains_lists_all(tmp_path):
    kstore.add("alpha", "t", "r", home=tmp_path)
    kstore.add("beta", "t", "r", home=tmp_path)
    assert set(kstore.domains(home=tmp_path)) == {"alpha", "beta"}


def test_unit_count(tmp_path):
    kstore.add("d", "t1", "r1", home=tmp_path)
    kstore.add("d", "t2", "r2", home=tmp_path)
    assert kstore.unit_count(home=tmp_path) == 2


def test_migrate_knowledge_from_sqlite(tmp_path):
    """Gammal hund.db med knowledge_units → brain/knowledge/*.json."""
    old_db = tmp_path / "hund.db"
    conn = sqlite3.connect(old_db)
    conn.execute("""CREATE TABLE knowledge_units (
        id TEXT, created_at TEXT, domain TEXT, trigger TEXT, rule TEXT,
        frequency INTEGER, last_used TEXT, success_count INTEGER,
        fail_count INTEGER, source TEXT)""")
    rows = []
    for i in range(3):
        rows.append((f"id-{i}", "2026-01-01", "shopify", f"trig{i}", f"rule{i}",
                     i, None, 0, 0, "study"))
    rows.append(("id-x", "2026-01-01", "general", "g", "gr", 0, None, 0, 0, "manual"))
    conn.executemany("INSERT INTO knowledge_units VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    report = migrate.migrate(home=tmp_path)
    assert report["domains"] == 2  # shopify + general
    assert report["units"] == 4
    shop = tmp_path / "brain" / "knowledge" / "shopify.json"
    assert shop.exists()
    import json

    data = json.loads(shop.read_text(encoding="utf-8"))
    assert len(data["units"]) == 3


def test_migrate_idempotent(tmp_path):
    old_db = tmp_path / "hund.db"
    conn = sqlite3.connect(old_db)
    conn.execute("""CREATE TABLE knowledge_units (
        id TEXT, created_at TEXT, domain TEXT, trigger TEXT, rule TEXT,
        frequency INTEGER, last_used TEXT, success_count INTEGER,
        fail_count INTEGER, source TEXT)""")
    conn.execute("INSERT INTO knowledge_units VALUES ('k1','t','d','tr','ru',0,NULL,0,0,'m')")
    conn.commit()
    conn.close()

    r1 = migrate.migrate(home=tmp_path)
    r2 = migrate.migrate(home=tmp_path)  # andra körningen
    assert r1["units"] == 1
    assert r2["units"] == 0  # inga nya — idempotent
    assert kstore.unit_count(home=tmp_path) == 1


def test_migrate_no_old_db_is_noop(tmp_path):
    """Utan gammal hund.db: strukturer skapas, noll units."""
    report = migrate.migrate(home=tmp_path)
    assert report["migrated"] is False
    assert report["units"] == 0
    assert (tmp_path / "brain" / "skills").exists()
    assert (tmp_path / "brain" / "knowledge").exists()


def test_migrate_moves_skills_and_policy(tmp_path):
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "x.json").write_text("{}", encoding="utf-8")
    (tmp_path / "policy.json").write_text("{}", encoding="utf-8")
    report = migrate.migrate(home=tmp_path)
    assert report["skills"] == 1
    assert report["policy"] is True
    assert (tmp_path / "brain" / "skills" / "x.json").exists()
    assert (tmp_path / "brain" / "policy.json").exists()
    assert not (tmp_path / "skills" / "x.json").exists()
