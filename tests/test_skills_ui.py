"""Tests for /skills 2-layer fullscreen UI and inspection views."""
from io import StringIO
from pathlib import Path
from rich.console import Console
import pytest

from hund.skills.model import Skill
from hund.skills.vault import SkillVault
from hund.ui.commands import CommandContext, cmd_skills
from hund.ui.skills_view import render_skill_detail, render_skills_panel


@pytest.fixture
def skills_home(tmp_path: Path) -> Path:
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir(parents=True, exist_ok=True)
    skills_dir = brain_dir / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_render_skills_panel_structure(skills_home: Path) -> None:
    vault = SkillVault(home=skills_home)
    panel = render_skills_panel(vault=vault, width=80)

    # 1. Double border frame
    assert "╔" in panel and "╗" in panel
    assert "╚" in panel and "╝" in panel
    assert "SKILLS" in panel
    assert "slots]" in panel

    # 2. Motor Skills section
    assert "MOTOR SKILLS" in panel
    assert "persona-preservation" in panel
    assert "shell-command-safety" in panel
    assert "context-condenser" in panel

    # 3. Domain Skills & Vault sections
    assert "DOMAIN SKILLS" in panel
    assert "VAULT" in panel
    assert "commands:" in panel


def test_render_skill_detail_view(skills_home: Path) -> None:
    vault = SkillVault(home=skills_home)
    detail = render_skill_detail("persona-preservation", vault=vault, width=80)

    assert "SKILL DETAIL: persona-preservation" in detail
    assert "Motor Instinct" in detail
    assert "Mastery / XP" in detail
    assert "Dependencies" in detail


def test_cmd_skills_dispatch_and_inspection(skills_home: Path) -> None:
    vault = SkillVault(home=skills_home)
    buf = StringIO()
    console = Console(file=buf, color_system=None, force_terminal=False, width=100)

    class DummyRT:
        skills = None

    ctx = CommandContext(console=console, rt=DummyRT(), state=None)

    # Test /skills overview
    cmd_skills(ctx, [])
    output = buf.getvalue()
    assert "SPECIALIZATIONS" in output
    assert "MOTOR SKILLS" not in output

    # Test /skills info <name>
    buf.seek(0)
    buf.truncate(0)
    cmd_skills(ctx, ["info", "file-operations"])
    output_info = buf.getvalue()
    assert "SKILL DETAIL: file-operations" in output_info
