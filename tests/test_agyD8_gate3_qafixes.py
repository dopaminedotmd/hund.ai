"""agyD/8 — Gate 3 live-QA fixes: banner specs, PRC min sample, human inspect."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from hund.stats import base_stats, epochs
from hund.ui.render import build_startup_banner
from hund.ui.screen_render import render_skills, skill_detail_lines
from hund.ui.snapshots import SkillItem, SkillsSnapshot


def _skill() -> SkillItem:
    return SkillItem(
        name="python-fastapi",
        domain="backend",
        xp=450,
        level=2,
        tier="Expert",
        percent=78,
        lifecycle_state="active",
        vault_state="equipped",
        triggers=("fastapi endpoint", "pydantic schema"),
        tools=("write_file",),
        safety_level="read_only",
        provenance=("k1@1.0",),
        when_to_use="Use when creating or maintaining FastAPI routes.",
        capability_id="backend/python-fastapi",
        scope="global",
        version="1.2.0",
        steps=("Define strongly typed Pydantic models.", "Verify behavior with pytest."),
        verification=("Routes return 200 or 201 on success.",),
        limitations=("No raw WebSocket handling.",),
    )


def _seed_tool_events(home: Path, success_count: int) -> None:
    (home / "logs").mkdir(parents=True, exist_ok=True)
    epochs.set_epoch(1, "2026-01-01T00:00:00+00:00", db_path=home / "hund.db")
    conn = sqlite3.connect(home / "logs" / "tool_events.db")
    conn.execute(
        """CREATE TABLE tool_events (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            tool TEXT,
            risk TEXT,
            outcome TEXT,
            success INTEGER DEFAULT 0
        )"""
    )
    stamp = datetime(2026, 1, 10, tzinfo=timezone.utc).isoformat()
    for index in range(success_count):
        conn.execute(
            "INSERT INTO tool_events VALUES (?, ?, 'bash', 'low', 'ran', 1)",
            (f"t{index}", stamp),
        )
    conn.commit()
    conn.close()


def test_precision_requires_minimum_sample_before_reporting(tmp_path: Path):
    # One successful tool call must NOT show 100%.
    _seed_tool_events(tmp_path, 1)
    stat = base_stats.compute_precision(home=tmp_path)
    assert stat["value"] is None and stat["tier"] == "—"

    # Three successes are enough to report.
    other = tmp_path / "three"
    _seed_tool_events(other, 3)
    stat3 = base_stats.compute_precision(home=other)
    assert stat3["value"] == 100.0


def test_startup_banner_shows_active_specialisations(monkeypatch):
    stats = {name: {"progress": 0} for name in ("clarity", "precision", "efficiency", "endurance", "mastery")}
    monkeypatch.setattr("hund.stats.compute_all", lambda: stats)
    active = [
        SimpleNamespace(domain="backend", name="python-fastapi"),
        SimpleNamespace(domain="backend", name="react-tui"),
        SimpleNamespace(domain="frontend", name="git-workflow"),
    ]
    monkeypatch.setattr("hund.skills.vault.SkillVault.get_active_skills", lambda self, workspace=None: active)
    monkeypatch.setattr("hund.skills.vault.SkillVault.get_core_skills", lambda self: [])
    monkeypatch.setattr("hund.ui.render.project_active_skill_xp", lambda skills, **kwargs: ())
    rt = SimpleNamespace(profile=SimpleNamespace(), cfg=None, workspace=None)

    banner = build_startup_banner(rt, width=100)
    assert "SPECIALISATIONS (2/6)" in banner
    assert "● backend" in banner
    assert "● frontend" in banner
    assert "No active specialisations" not in banner


def test_skill_detail_is_human_readable_not_raw_json():
    text = "\n".join(skill_detail_lines(_skill()))
    assert "name: python-fastapi" in text
    assert "domain: backend" in text
    assert "steps:" in text and "1. Define strongly typed Pydantic models." in text
    assert "- Routes return 200 or 201 on success." in text
    assert '- No raw WebSocket handling.' in text
    assert '"{' not in text and '"name": "python-fastapi"' not in text
    # All fields are present (nothing curated away).
    assert "lifecycle: active · vault: [equipped]" in text


def test_skill_detail_footer_advertises_edit_mode():
    snap = SkillsSnapshot(equipped=(_skill(),), parked=())
    out = render_skills(snap, width=80, height=24, detail_name="python-fastapi")
    assert "[e] Edit Mode" in out
    assert "[c] Copy All" in out
