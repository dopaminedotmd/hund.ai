"""Fas 9.5 Del B — sessions-arkiv + FTS5-sök.

Verifierar: create (aktiv markering), add_message (count + title), ordning,
history (user/assistant only), fulltext-sök, delete (session+messages+fts),
prefix-resolving, set_active.
"""
from __future__ import annotations

from hund.agent import sessions as S


def test_create_returns_id_and_marks_active(tmp_path):
    s1 = S.create(home=tmp_path)
    assert len(s1) == 32  # uuid hex
    assert S.get_active(home=tmp_path)["id"] == s1
    s2 = S.create(home=tmp_path)
    active = S.get_active(home=tmp_path)
    assert active["id"] == s2  # nyaste aktiv, s1 deaktiverad


def test_add_message_increments_count_and_sets_title(tmp_path):
    sid = S.create(home=tmp_path)
    S.add_message(sid, "user", "hur lägger jag till en skill?", home=tmp_path)
    S.add_message(sid, "assistant", "kör hund skills add", home=tmp_path)
    info = S.info(sid, home=tmp_path)
    assert info["message_count"] == 2
    assert "skill" in info["title"]


def test_list_messages_preserves_order(tmp_path):
    sid = S.create(home=tmp_path)
    S.add_message(sid, "user", "först", home=tmp_path)
    S.add_message(sid, "assistant", "andra", home=tmp_path)
    S.add_message(sid, "user", "tredje", home=tmp_path)
    msgs = S.list_messages(sid, home=tmp_path)
    assert [c for _, c in msgs] == ["först", "andra", "tredje"]


def test_history_excludes_system_and_tool(tmp_path):
    sid = S.create(home=tmp_path)
    S.add_message(sid, "user", "fråga", home=tmp_path)
    S.add_message(sid, "assistant", "svar", home=tmp_path)
    S.add_message(sid, "tool", "output-data", home=tmp_path)
    hist = S.history(sid, home=tmp_path)
    roles = [r for r, _ in hist]
    assert roles == ["user", "assistant"]
    assert all("output-data" not in c for _, c in hist)


def test_fulltext_search_finds_content(tmp_path):
    sid = S.create(home=tmp_path)
    S.add_message(sid, "user", "hur migrerar jag databasen?", home=tmp_path)
    S.add_message(sid, "assistant", "kör hund migrate", home=tmp_path)
    hits = S.search("migrerar", home=tmp_path)
    assert hits
    session_id, role, snip, _ = hits[0]
    assert session_id == sid
    assert "migrerar" in snip.lower() or "migrer" in snip.lower()


def test_search_empty_query_returns_empty(tmp_path):
    sid = S.create(home=tmp_path)
    S.add_message(sid, "user", "något", home=tmp_path)
    assert S.search("   ", home=tmp_path) == []


def test_delete_removes_session_messages_and_fts(tmp_path):
    sid = S.create(home=tmp_path)
    S.add_message(sid, "user", "unikterm_xyz raderamig", home=tmp_path)
    assert S.search("unikterm_xyz", home=tmp_path)
    n = S.delete(sid, home=tmp_path)
    assert n == 1
    assert S.info(sid, home=tmp_path) is None
    assert S.search("unikterm_xyz", home=tmp_path) == []
    assert S.list_messages(sid, home=tmp_path) == []


def test_prefix_resolve(tmp_path):
    sid = S.create(home=tmp_path)
    S.add_message(sid, "user", "prefix-test", home=tmp_path)
    prefix = sid[:8]
    assert S.info(prefix, home=tmp_path)["id"] == sid
    assert S.delete(prefix, home=tmp_path) == 1


def test_set_active_by_prefix(tmp_path):
    s1 = S.create(home=tmp_path)
    s2 = S.create(home=tmp_path)
    assert S.get_active(home=tmp_path)["id"] == s2
    assert S.set_active(s1[:8], home=tmp_path) == 1
    assert S.get_active(home=tmp_path)["id"] == s1


def test_list_sessions_newest_first(tmp_path):
    a = S.create(home=tmp_path)
    b = S.create(home=tmp_path)
    rows = S.list_sessions(home=tmp_path)
    ids = [r[0] for r in rows]
    assert ids == [b, a]
