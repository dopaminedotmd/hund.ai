"""agyD/2 — Gate 3 §2.2: /stats full destination layout (velocity chart, deltas, spec rows)."""
from datetime import date, timedelta

from hund.ui.screen_render import render_stats, stats_lines
from hund.ui.snapshots import SpecializationItem, StatItem, StatsSnapshot


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
    days = tuple(date(2026, 9, 3) - timedelta(days=i) for i in range(6, -1, -1))
    return StatsSnapshot(
        "0.2.0", stats, specs, (1, 2, 0, 3, 5, 6, 7), days,
        (("clarity", 2.4, True), ("precision", 4.2, True)), True,
    )


def test_stats_full_has_sections_and_vertical_chart():
    lines = stats_lines(_snapshot(), width=100)
    text = "\n".join(lines)
    assert "SPECIALISATIONS (2)" in text
    assert "7-DAY VELOCITY" in text
    assert "BASE STAT DELTAS" in text
    assert "[active]" in text
    assert "┤" in text  # vertical chart axis


def test_stats_full_renders_title_and_axis_letters():
    out = render_stats(_snapshot(), width=100, height=40)
    assert "FULL VELOCITY & TRENDS" in out
    # Day letters on the axis row (M T W T F S S)
    axis = [ln for ln in out.splitlines() if "└─" in ln or "M" in ln]
    assert axis
