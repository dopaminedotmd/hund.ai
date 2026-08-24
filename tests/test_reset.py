"""Unit tests for the hund reset command and data wipe."""
import json
from pathlib import Path

from hund.domains.confidence import _ensure_table as _ensure_conf_table, add_signal
from hund.domains.xp import _ensure_table as _ensure_xp_table, add_xp, get_xp
from hund.learning.observer import add_gap_event, list_gap_events
from hund.reset import reset_all_progress
from hund.store.sqlite import connect


def test_reset_all_progress_cleans_tables_and_files(tmp_path: Path) -> None:
    home = tmp_path / "hund_home"
    home.mkdir()
    db_file = home / "hund.db"

    # 1. Populate DB tables
    _ensure_xp_table(db_file)
    _ensure_conf_table(db_file)
    add_xp("python", 500, db_path=db_file)
    add_signal("python", "user_declaration", db_path=db_file)

    # 2. Populate log & telemetry DB tables (Base stats sources)
    logs_dir = home / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    req_db = logs_dir / "requests.db"
    conn_req = connect(req_db)
    conn_req.execute(
        "CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, prompt_tokens INTEGER, completion_tokens INTEGER)"
    )
    conn_req.execute("INSERT INTO requests VALUES ('r1', 100, 50)")
    conn_req.commit()
    conn_req.close()

    tool_db = logs_dir / "tool_events.db"
    conn_tool = connect(tool_db)
    conn_tool.execute(
        "CREATE TABLE IF NOT EXISTS tool_events (id TEXT PRIMARY KEY, tool TEXT, outcome TEXT, success INTEGER)"
    )
    conn_tool.execute("INSERT INTO tool_events VALUES ('t1', 'read_file', 'ran', 1)")
    conn_tool.commit()
    conn_tool.close()

    # 3. Populate knowledge units
    k_dir = home / "brain" / "knowledge"
    k_dir.mkdir(parents=True, exist_ok=True)
    (k_dir / "python.json").write_text(json.dumps({"domain": "python", "units": [{"rule": "test"}]}), encoding="utf-8")

    # 4. Populate custom skills & vault state
    s_dir = home / "brain" / "skills"
    s_dir.mkdir(parents=True, exist_ok=True)
    (s_dir / "custom-skill.json").write_text(json.dumps({"name": "custom-skill"}), encoding="utf-8")
    (home / "brain" / "skill_state.json").write_text(json.dumps({"active": ["custom-skill"]}), encoding="utf-8")

    # 5. Create config.json (must NOT be deleted!)
    config_file = home / "config.json"
    config_file.write_text(json.dumps({"provider": {"model": "test-model"}}), encoding="utf-8")

    # Execute reset
    results = reset_all_progress(home=home)
    assert len(results) > 0

    # Verify tables cleared
    py_xp = get_xp("python", db_path=db_file)
    assert py_xp["xp"] == 0

    # Verify log tables cleared
    conn_req = connect(req_db)
    assert conn_req.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0
    conn_req.close()

    conn_tool = connect(tool_db)
    assert conn_tool.execute("SELECT COUNT(*) FROM tool_events").fetchone()[0] == 0
    conn_tool.close()

    # Verify knowledge units removed
    assert not list(k_dir.glob("*.json"))

    # Verify custom skills removed
    assert not list(s_dir.glob("*.json"))
    assert not (home / "brain" / "skill_state.json").exists()

    # Verify config PRESERVED
    assert config_file.exists()
    assert "test-model" in config_file.read_text(encoding="utf-8")

    # Idempotent second run
    results2 = reset_all_progress(home=home)
    assert "Already clean" in results2[0]
