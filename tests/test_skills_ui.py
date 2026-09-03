"""Tests for /skills 2-layer fullscreen UI and inspection views."""
from io import StringIO
from pathlib import Path
from rich.console import Console
import pytest

from hund.skills.model import Skill
from hund.skills.vault import SkillVault
from hund.ui.commands import CommandContext, cmd_skills
from hund.ui.skills_view import render_skill_detail, render_skills_panel
from hund.ui.screen_render import skill_detail_lines
from hund.ui.snapshots import SkillItem
from hund.skills.projection import SkillXPProjectionRow


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
    assert "slots]" not in panel

    # 2. Motor Skills section
    assert "MOTOR SKILLS" in panel
    assert "persona-preservation" in panel
    assert "shell-command-safety" in panel
    assert "context-condenser" in panel

    # 3. Active Skill-XP and Vault sections
    assert "ACTIVE SKILLS" in panel
    assert "Skill XP" in panel
    assert "VAULT" in panel
    assert "commands:" in panel


def test_render_skills_panel_uses_shared_skill_xp_projection(monkeypatch, skills_home: Path) -> None:
    vault = SkillVault(home=skills_home)
    skill = Skill(
        schema_version=1,
        name="domain-name-must-not-drive-proficiency",
        domain="domain-with-unrelated-xp",
        status="active",
        triggers=("test",),
        when_to_use="When testing.",
        steps=("Verify.",),
        required_tools=(),
        forbidden_actions=(),
        safety_level="read_only",
        verification=("Verify.",),
        capability_id="canonical-capability",
        lifecycle_state="active",
        vault_state="equipped",
    )
    monkeypatch.setattr(vault, "get_active_skills", lambda workspace=None: [skill])
    monkeypatch.setattr(
        "hund.ui.skills_view.project_active_skill_xp",
        lambda skills, **kwargs: (
            SkillXPProjectionRow("canonical-capability", "Canonical display", 42, 1, "Novice", 84, 42, 8, None),
        ),
        raising=False,
    )

    panel = render_skills_panel(vault=vault, width=100)

    assert "Canonical display" in panel
    assert "42 Skill XP" in panel
    assert "Lvl 1" in panel


def test_render_skill_detail_view(skills_home: Path) -> None:
    vault = SkillVault(home=skills_home)
    detail = render_skill_detail("persona-preservation", vault=vault, width=80)

    assert "SKILL DETAIL: persona-preservation" in detail
    assert "Motor Instinct" in detail
    assert "Mastery / XP" in detail
    assert "Dependencies" in detail


def test_snapshot_skill_detail_exposes_canonical_procedure_and_identity() -> None:
    item = SkillItem(
        name="marketing",
        domain="general",
        xp=0,
        level=1,
        tier="Novice",
        percent=0,
        lifecycle_state="active",
        vault_state="equipped",
        triggers=("marketing review",),
        tools=("read_file",),
        safety_level="read_only",
        provenance=("local-authoring",),
        when_to_use="When planning a marketing campaign.",
        capability_id="general/marketing",
        scope="project",
        version="1.0.0",
        steps=("Define the audience.", "Review channel fit."),
        verification=("Confirm claims have evidence.",),
        limitations=("No paid-media execution.",),
    )

    rendered = "\n".join(skill_detail_lines(item))

    assert "Capability: general/marketing" in rendered
    assert "Scope: project" in rendered
    assert "Version: 1.0.0" in rendered
    assert "1. Define the audience." in rendered
    assert "Verification:" in rendered
    assert "Confirm claims have evidence." in rendered
    assert "No paid-media execution." in rendered


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
    assert "SKILLS" in output
    assert "MOTOR SKILLS" not in output

    # Test /skills info <name>
    buf.seek(0)
    buf.truncate(0)
    cmd_skills(ctx, ["info", "file-operations"])
    output_info = buf.getvalue()
    assert "SKILL DETAIL: file-operations" in output_info


def test_zero_personal_xp_invariant_all_stages():
    from hund.skills.authoring import PublicationReceipt, render_publication_receipt
    from hund.skills.model import Skill

    skill = Skill(
        schema_version=1,
        name="test-xp",
        domain="general",
        status="active",
        triggers=("test",),
        when_to_use="When testing.",
        steps=("Step 1",),
        required_tools=(),
        forbidden_actions=("modify_tcb", "self_update", "apply_update", "elevate_permissions"),
        safety_level="read_only",
        verification=("Verify",),
    )
    assert skill.personal_skill_xp == 0
    assert skill.to_dict()["personal_skill_xp"] == 0

    receipt = PublicationReceipt(
        skill_name="test-xp",
        capability_id="general/test-xp",
        scope="global",
        action="created",
        version="1.0.0",
        lifecycle_state="active",
        vault_state="vaulted",
        personal_skill_xp=skill.personal_skill_xp,
        source_count=0,
        validation_checks=("schema_and_manifest",),
    )
    rendered = render_publication_receipt(receipt)
    assert "0 XP" in rendered


def test_personal_skill_xp_rendered_as_zero():
    from hund.skills.authoring import PublicationReceipt, render_publication_receipt

    receipt = PublicationReceipt(
        skill_name="my-skill",
        capability_id="general/my-skill",
        scope="project",
        action="created",
        version="1.0.0",
        lifecycle_state="active",
        vault_state="equipped",
        personal_skill_xp=0,
        source_count=1,
        validation_checks=("schema_and_manifest",),
    )
    text = render_publication_receipt(receipt)
    assert "0 XP" in text
    assert "1 authoritative reference(s)" in text


def test_receipt_rendering_width_and_ascii():
    from hund.skills.authoring import PublicationReceipt, render_publication_receipt

    receipt = PublicationReceipt(
        skill_name="markdown-table-formatter",
        capability_id="general/markdown-table-formatter",
        scope="global",
        action="created",
        version="1.0.0",
        lifecycle_state="active",
        vault_state="equipped",
        personal_skill_xp=0,
        source_count=2,
        validation_checks=("schema_and_manifest", "loader_roundtrip"),
        diff_summary="Added table column padding alignment rules and multiline cell support",
        limitations=("Requires clean markdown inputs",),
    )

    # Test widths: 42, 60, 80, 120
    for width in (42, 60, 80, 120):
        rendered = render_publication_receipt(receipt, width=width)
        for line in rendered.splitlines():
            assert len(line) <= max(width + 5, 20)  # textwrap boundaries

    # Test ASCII fallback
    rendered_ascii = render_publication_receipt(receipt, width=80, ascii_only=True)
    assert "·" not in rendered_ascii
    assert "|" in rendered_ascii or "*" in rendered_ascii


def test_dynamic_context_message_pinned_skill_injection():
    from hund.agent.loop import _dynamic_context_message
    from hund.skills.model import Skill

    pinned = Skill(
        schema_version=1,
        name="pinned-css-formatter",
        domain="styling",
        status="active",
        triggers=("format css", "style css"),
        when_to_use="When formatting CSS style sheets.",
        steps=("Sort declarations alphabetically.", "Indent 2 spaces."),
        required_tools=(),
        forbidden_actions=(),
        safety_level="read_only",
        verification=("CSS syntax is valid.",),
        lifecycle_state="active",
        vault_state="equipped",
    )

    other = Skill(
        schema_version=1,
        name="other-skill",
        domain="general",
        status="active",
        triggers=("other trigger",),
        when_to_use="When doing other stuff.",
        steps=("Step 1",),
        required_tools=(),
        forbidden_actions=(),
        safety_level="read_only",
        verification=("Other passes.",),
        lifecycle_state="active",
        vault_state="equipped",
    )

    # When pinned_skill is provided:
    # 1. It appears under the pinned header with instructions
    msg = _dynamic_context_message(
        skills=[pinned, other],
        user_text="format css and other trigger",
        workspace_id="test_ws",
        pinned_skill=pinned,
    )
    assert msg is not None
    content = msg.content
    assert "## Nyligen skapad & aktiv skill (prio: instruktioner)" in content
    assert "pinned-css-formatter" in content
    assert "Sort declarations alphabetically." in content
    # 2. Pinned skill is filtered from summaries to avoid duplication
    if "## Relevanta skills" in content:
        summaries_part = content.split("## Relevanta skills")[1]
        assert "pinned-css-formatter" not in summaries_part
        assert "other-skill" in summaries_part


def test_pinned_skill_absent_after_turn_injects_no_created_header():
    """Track 3: once the pinned skill expired (None), the next turn carries no
    'recently created skill' header — the pin is strictly one turn."""
    from hund.agent.loop import _dynamic_context_message
    from hund.skills.model import Skill

    skill = Skill(
        schema_version=1,
        name="expired-pinned-html",
        domain="design",
        status="active",
        triggers=("expired html",),
        when_to_use="When building expired html pages.",
        steps=("Create the html skeleton.", "Verify the page."),
        required_tools=(),
        forbidden_actions=(),
        safety_level="read_only",
        verification=("Page renders.",),
        lifecycle_state="active",
        vault_state="equipped",
    )

    # Turn N+1: pin present -> created-header is injected.
    msg_pinned = _dynamic_context_message(
        skills=[skill],
        user_text="expired html",
        workspace_id="test_ws",
        pinned_skill=skill,
    )
    assert msg_pinned is not None
    assert "## Nyligen skapad & aktiv skill (prio: instruktioner)" in msg_pinned.content

    # Turn N+2: pin expired (None) -> never inject the created-header again,
    # even though the same skill still exists in the equipped list.
    msg_after = _dynamic_context_message(
        skills=[skill],
        user_text="expired html",
        workspace_id="test_ws",
        pinned_skill=None,
    )
    assert msg_after is None or (
        "## Nyligen skapad & aktiv skill (prio: instruktioner)" not in msg_after.content
    )

