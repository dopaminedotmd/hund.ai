"""agyD/5 — Gate 3 §2.5.1: Skill Inspect shows the exact, full definition."""
import json

from hund.ui.screen_render import (
    render_skills,
    skill_definition_text,
    skill_detail_lines,
)
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
        triggers=("fastapi endpoint", "pydantic schema", "Depends()"),
        tools=("write_file", "terminal"),
        safety_level="safe",
        provenance=("k1@1.0",),
        when_to_use="Use when creating or maintaining FastAPI routes.",
        capability_id="backend/python-fastapi",
        scope="global",
        version="1.2.0",
        steps=(
            "Define strongly typed Pydantic models.",
            "Implement endpoint handler with APIRouter.",
            "Verify behavior with pytest.",
        ),
        verification=(
            "Routes return 200 or 201 on success.",
            "Invalid payloads return HTTP 422.",
        ),
        limitations=("No raw WebSocket handling (delegate to fast-ws).",),
    )


def test_detail_is_exact_full_definition_without_curation():
    lines = skill_detail_lines(_skill())
    text = "\n".join(lines)
    # Every trigger, step, verification rule and limitation appears in full,
    # human-readable (no JSON noise, nothing curated away).
    for fragment in (
        "name: python-fastapi",
        "safety: safe",
        "scope: global",
        "when_to_use:",
        "Use when creating or maintaining FastAPI routes.",
        "fastapi endpoint",
        "pydantic schema",
        "Depends()",
        "1. Define strongly typed Pydantic models.",
        "3. Verify behavior with pytest.",
        "- Routes return 200 or 201 on success.",
        "- No raw WebSocket handling (delegate to fast-ws).",
        "xp: 450 XP · level: 2 · Expert · progress: 78%",
    ):
        assert fragment in text
    assert "Procedure:" not in text  # curated summary is gone
    assert "None declared" not in text


def test_definition_text_is_json_roundtrippable():
    text = skill_definition_text(_skill())
    data = json.loads(text)
    assert data["name"] == "python-fastapi"
    assert data["steps"] == [
        "Define strongly typed Pydantic models.",
        "Implement endpoint handler with APIRouter.",
        "Verify behavior with pytest.",
    ]
    assert data["level"] == 2 and data["progress_percent"] == 78


def test_detail_render_has_dedicated_title_meta_and_scroll_footer():
    snap = SkillsSnapshot(equipped=(_skill(),), parked=())
    out = render_skills(snap, width=80, height=24, detail_name="python-fastapi")
    assert out.splitlines()[0].startswith("╔ SKILL DETAIL · python-fastapi")
    assert "L2 · 78%" in out.splitlines()[0]
    assert "[c] Copy All" in out
    assert "[←] Back" in out
    # Catalog chrome must not leak into detail.
    assert "── SKILLS (1)" not in out
    assert "Enter Inspect/Manage" not in out


def test_detail_ascii_fallback_geometry():
    snap = SkillsSnapshot(equipped=(_skill(),), parked=())
    out = render_skills(snap, width=80, height=24, detail_name="python-fastapi", ascii_only=True)
    assert "╔" not in out
    assert out.splitlines()[0].startswith("+")
    assert max(len(line) for line in out.splitlines()) <= 79
