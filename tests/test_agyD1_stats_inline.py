"""agyD/1 — Gate 3 §2.1: /stats inline chat card rendering."""
from datetime import date

from hund.ui.screen_render import render_stats_inline
from hund.ui.snapshots import SkillProposalItem, SkillItem, SkillsSnapshot, SpecializationItem, StatItem, StatsSnapshot


def _snapshot() -> StatsSnapshot:
    stats = (
        StatItem("Clarity", "CLR", 78.0, 78, "B"),
        StatItem("Precision", "PRC", 94.0, 94, "A"),
        StatItem("Efficiency", "EFF", 82.0, 82, "B"),
        StatItem("Endurance", "END", 80.0, 80, "B"),
        StatItem("Mastery", "MAS", 65.0, 65, "B"),
    )
    specs = (
        SpecializationItem("fullstack-builder", "fullstack", 3, "Expert", 62, 120, "active", "equipped", True),
        SpecializationItem("machine-doctor", "machine", 2, "Advanced", 48, 80, "active", "equipped", False),
    )
    days = tuple(date(2026, 9, 3) - __import__("datetime").timedelta(days=i) for i in range(6, -1, -1))
    return StatsSnapshot(
        "0.2.0", stats, specs, (1, 2, 0, 3, 4, 5, 6), days,
        (("clarity", 12.0, True),), True,
        xp_today=240, verified_today=3, velocity_today_pct=12,
    )


def test_inline_card_has_double_frame_and_four_quadrants():
    out = render_stats_inline(_snapshot(), width=80)
    assert out.startswith("╔═ STATS")
    assert out.endswith("╝")
    assert "BASE STATS" in out
    assert "ACTIVE SKILLS" in out
    assert "SPECIALISATIONS" in out
    assert "TODAY & PROGRESS" in out
    assert "fullstack-builder" in out
    assert "+240 XP" in out


def test_inline_card_ascii_fallback():
    out = render_stats_inline(_snapshot(), width=70, ascii_only=True)
    assert out.startswith("+- STATS")


def test_inline_card_narrow_single_column():
    out = render_stats_inline(_snapshot(), width=44)
    assert "BASE STATS" in out
    assert "TODAY & PROGRESS" in out
