"""Tests for Gate A7: Startup and /stats truthful labels and geometry width synchronization."""
import pytest
from datetime import date
from types import SimpleNamespace

from hund.ui.render import build_startup_banner
from hund.ui.screen_render import stats_lines, render_stats, fullscreen_frame
from hund.ui.snapshots import StatsSnapshot, StatItem, SpecializationItem


class TestStartupAndStatsTruth:
    def _create_stats_snapshot(self, long_names: bool = False) -> StatsSnapshot:
        stats = (
            StatItem("clarity", "CLR", 85.0, 85, "Expert"),
            StatItem("precision", "PRC", 90.0, 90, "Master"),
            StatItem("efficiency", "EFF", 75.0, 75, "Adept"),
            StatItem("endurance", "END", 60.0, 60, "Apprentice"),
            StatItem("mastery", "MAS", 70.0, 70, "Adept"),
        )
        name1 = "very-long-project-specific-deployment-pipeline-checklist" if long_names else "api-checklist"
        name2 = "secondary-database-maintenance-worker" if long_names else "db-sync"
        specializations = (
            SpecializationItem(name1, "devops", 1, "Novice", 10, 50, "active", "equipped", False),
            SpecializationItem(name2, "backend", 2, "Apprentice", 30, 150, "active", "equipped", True),
        )
        today = date.today()
        dates = tuple(today for _ in range(7))
        activity = (0, 1, 2, 0, 3, 1, 2)
        velocity = (("clarity", 5.0, True),)
        return StatsSnapshot(
            version="0.1.0",
            stats=stats,
            specializations=specializations,
            activity=activity,
            activity_dates=dates,
            velocity=velocity,
            has_activity=True,
        )

    def test_startup_banner_uses_active_skills_label(self):
        rt = SimpleNamespace(
            profile=None,
            workspace=None,
            cfg=SimpleNamespace(provider=SimpleNamespace(provider_id="deepseek", model="deepseek-chat")),
        )
        banner = build_startup_banner(rt, width=80)
        assert "ACTIVE SKILLS" in banner
        assert "SPECIALIZATIONS" not in banner

    def test_stats_screen_uses_active_skills_label(self):
        snap = self._create_stats_snapshot()
        lines = stats_lines(snap, width=80)
        text = "\n".join(lines)
        assert "ACTIVE SKILLS" in text
        assert "SPECIALIZATIONS" not in text

    @pytest.mark.parametrize("width", [120, 80, 72, 60, 42])
    def test_stats_frame_no_cross_column_continuation_wrapping(self, width: int):
        snap = self._create_stats_snapshot(long_names=True)
        rendered = render_stats(snap, width=width, height=24)
        # Check that no line in rendered output exceeds the frame width
        lines = rendered.splitlines()
        for idx, line in enumerate(lines):
            # Length should match expected terminal/frame width
            assert len(line) <= width, f"Line {idx} exceeds width {width}: {line}"
            # Ensure borders are aligned and content doesn't split awkwardly into column 0
            if line.startswith("║") or line.startswith("|"):
                assert line.endswith("║") or line.endswith("|")
