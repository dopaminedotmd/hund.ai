"""Unit tests for the fullscreen startup banner per TUI_FACIT.md §4."""
from types import SimpleNamespace
from unittest.mock import MagicMock
from hund.ui.render import build_startup_banner
from hund.ui.fullscreen import _lex_banner_line, _OutputLexer
from hund.skills.projection import SkillXPProjectionRow
from prompt_toolkit.document import Document
from hund.ui.unicode_cells import cell_width


def test_build_startup_banner_structure_and_width() -> None:
    W = 80
    mock_rt = SimpleNamespace(
        profile=SimpleNamespace(
            os_caption="Windows 11 Pro",
            hostname="razor",
            processor="Intel Core i7-8550U",
            cpu_count=4,
            total_ram_gb=16.0,
            gpu_model="Intel UHD Graphics 620",
            gpu_vram_mb=128,
            shell="PowerShell",
        ),
        cfg=SimpleNamespace(
            provider=SimpleNamespace(
                name="DeepSeek",
                model="deepseek-v4-pro",
            )
        ),
    )

    banner = build_startup_banner(mock_rt, width=W)
    lines = banner.split("\n")

    assert lines[0].startswith("╔") and lines[0].endswith("╗")
    assert lines[-1].startswith("╚") and lines[-1].endswith("╝")

    # Every single line must match the width W
    for i, line in enumerate(lines):
        assert len(line) == W, f"Line {i} length {len(line)} != {W}: {line}"

    # Header and telemetry
    assert "▄▄" in banner
    assert "████▄" in banner
    assert "OS      Windows 11 Pro" in banner
    assert "HOST    razor" in banner
    assert "CPU     i7-8550U (4 cores)" in banner
    assert "RAM     16.0 GB" in banner
    assert "MODEL   deepseek-v4-pro" in banner

    # Base attributes and skills
    assert "── BASE STATS" in banner
    assert "── ACTIVE SKILLS" in banner
    assert "CLR Clarity" in banner
    assert "PRC Precision" in banner
    assert "EFF Efficiency" in banner
    assert "END Endurance" in banner
    assert "MAS Mastery" in banner
    assert "commands: /skills · /stats · /theme · /model · /clear · /exit" in banner


def test_banner_lexer_tokenization() -> None:
    top_line = "╔═ ▄▄                   ▄▄ ════════════════════════════════════════════════════╗"
    logo_line = "║  ████▄ ██ ██ ████▄ ▄████                                                     ║"
    header_line = "║  ── BASE STATS ───────               │  ── SPECIALIZATIONS (6/6) ──────────  ║"
    stat_line = "║  CLR Clarity    ████████░░ 72%       │  code-surgeon       ████████░░ 74%    ║"
    cmd_line = "║  commands: /skills · /stats · /theme · /model · /clear · /exit               ║"
    bot_line = "╚══════════════════════════════════════════════════════════════════════════════╝"

    toks_top = _lex_banner_line(top_line)
    assert toks_top[0][0] == "class:accent"
    assert any(t[0] == "class:logo" and "▄▄" in t[1] for t in toks_top)

    toks_logo = _lex_banner_line(logo_line)
    assert any(t[0] == "class:logo" and "████▄" in t[1] for t in toks_logo)

    toks_hdr = _lex_banner_line(header_line)
    assert any(t[0] == "class:header" and "BASE STATS" in t[1] for t in toks_hdr)
    assert any(t[0] == "class:secondary" and "│" in t[1] for t in toks_hdr)

    toks_stat = _lex_banner_line(stat_line)
    assert any(t[0] == "class:accent bold" and "CLR" in t[1] for t in toks_stat)
    assert any(t[0] == "class:learning" and "██" in t[1] for t in toks_stat)
    assert any(t[0] == "class:primary" and "code-surgeon" in t[1] for t in toks_stat)

    toks_cmd = _lex_banner_line(cmd_line)
    assert any(t[0] == "class:secondary" and "commands:" in t[1] for t in toks_cmd)

    toks_bot = _lex_banner_line(bot_line)
    assert toks_bot[0][0] == "class:accent"


def test_compact_banner_keeps_modern_stat_colours() -> None:
    compact_stat = "║  CLR Clarity   ██████████ 72%  ║"
    tokens = _lex_banner_line(compact_stat)
    assert any(style == "class:accent bold" and text == "CLR" for style, text in tokens)
    assert any(style == "class:learning" and "██" in text for style, text in tokens)
    assert any(style == "class:secondary" and "72%" in text for style, text in tokens)


def test_truncated_xp_rows_keep_semantic_colours_during_resize() -> None:
    truncated = "║  CLR Clarity   ███░░       ║"
    tokens = _lex_banner_line(truncated)
    assert any(style == "class:accent bold" and text == "CLR" for style, text in tokens)
    assert any(style == "class:learning" and text == "███░░" for style, text in tokens)

    skill_without_percentage = "║  html-coding    ██░         ║"
    skill_tokens = _lex_banner_line(skill_without_percentage)
    assert any(style == "class:learning" and text == "██░" for style, text in skill_tokens)


def test_banner_responsive_widths() -> None:
    mock_rt = SimpleNamespace(
        profile=SimpleNamespace(
            os_caption="Windows 11 Pro",
            hostname="razor",
            processor="Intel Core i7-8550U",
            cpu_count=4,
            total_ram_gb=16.0,
            gpu_model="Intel UHD Graphics 620",
            gpu_vram_mb=128,
            shell="PowerShell",
        ),
        cfg=None,
    )

    for test_w in (24, 39, 59, 60, 72, 80, 100):
        banner = build_startup_banner(mock_rt, width=test_w)
        lines = banner.splitlines()
        for i, line in enumerate(lines):
            assert len(line) == test_w, f"W={test_w}, line {i}: {len(line)} != {test_w}"


def test_startup_layout_stacks_truthful_specialisations_and_defensively_caps_projection(monkeypatch) -> None:
    stats = {name: {"progress": 0} for name in ("clarity", "precision", "efficiency", "endurance", "mastery")}
    rows = tuple(
        SkillXPProjectionRow(
            capability_id=f"cap-{index}",
            display_name=f"Skill {index}",
            total_xp=100 - index,
            level=2,
            tier="Apprentice",
            progress_percent=50,
            xp_into_level=50,
            xp_to_next_level=50,
            last_used_at=None,
        )
        for index in range(6)
    )
    monkeypatch.setattr("hund.stats.compute_all", lambda: stats)
    monkeypatch.setattr("hund.skills.vault.SkillVault.get_active_skills", lambda self, workspace=None: [])
    monkeypatch.setattr("hund.skills.vault.SkillVault.get_core_skills", lambda self: [])
    monkeypatch.setattr("hund.ui.render.project_active_skill_xp", lambda skills, **kwargs: rows)
    rt = SimpleNamespace(profile=SimpleNamespace(), cfg=None, workspace=None)

    for width in (120, 80, 60, 42):
        banner = build_startup_banner(rt, width=width)
        assert all(cell_width(line) == width for line in banner.splitlines())
        assert "SPECIALISATIONS (0/6)" in banner
        assert "No active specialisations" in banner
        assert "Skill 0" in banner and "Skill 4" in banner
        assert "Skill 5" not in banner
        base_index = banner.index("── BASE STATS")
        skills_index = banner.index("── ACTIVE SKILLS")
        specialisations_index = banner.index("SPECIALISATIONS (0/6)")
        assert base_index < skills_index < specialisations_index
        if width < 72:
            assert " │  " not in banner[base_index:specialisations_index]
        else:
            assert " │  " in banner[base_index:specialisations_index]


def test_startup_banner_is_cell_safe_for_wide_unicode_telemetry_and_ascii_no_color(monkeypatch) -> None:
    stats = {name: {"progress": 0} for name in ("clarity", "precision", "efficiency", "endurance", "mastery")}
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr("hund.stats.compute_all", lambda: stats)
    monkeypatch.setattr("hund.skills.vault.SkillVault.get_active_skills", lambda self, workspace=None: [])
    monkeypatch.setattr("hund.skills.vault.SkillVault.get_core_skills", lambda self: [])
    monkeypatch.setattr(
        "hund.ui.render.project_active_skill_xp",
        lambda skills, **kwargs: (
            SkillXPProjectionRow("cap", "技能開発👩‍💻e\u0301" * 5, 50, 1, "Novice", 50, 25, 25, None),
        ),
    )
    profile = SimpleNamespace(hostname="漢字" * 40)
    rt = SimpleNamespace(profile=profile, cfg=SimpleNamespace(ascii_ui=True), workspace=None)

    banner = build_startup_banner(rt, width=42)

    assert all(cell_width(line) == 42 for line in banner.splitlines())
    assert "\x1b" not in banner
    assert all(ord(char) < 128 for char in banner)


def test_startup_ascii_mode_requires_an_explicit_true_flag() -> None:
    """An unspecified mock configuration must retain the Unicode startup contract."""
    rt = SimpleNamespace(profile=SimpleNamespace(), cfg=MagicMock(), workspace=None)

    banner = build_startup_banner(rt, width=80)

    assert "── BASE STATS" in banner
    assert "╔" in banner


def test_banner_breakpoint_preserves_full_percentages(monkeypatch) -> None:
    stats = {
        name: {"progress": 100}
        for name in ("clarity", "precision", "efficiency", "endurance", "mastery")
    }
    skill = SimpleNamespace(
        name="code-surgeon",
        domain="code",
        capability_id="code-surgeon",
        lifecycle_state="active",
        vault_state="equipped",
    )
    monkeypatch.setattr("hund.stats.compute_all", lambda: stats)
    monkeypatch.setattr("hund.skills.vault.SkillVault.get_active_skills", lambda self, workspace=None: [skill])
    monkeypatch.setattr("hund.skills.vault.SkillVault.get_core_skills", lambda self: [])
    monkeypatch.setattr(
        "hund.ui.render.project_active_skill_xp",
        lambda skills, **kwargs: (
            SkillXPProjectionRow("code-surgeon", "code-surgeon", 100, 2, "Apprentice", 100, 50, 0, None),
        ),
        raising=False,
    )
    rt = SimpleNamespace(profile=SimpleNamespace(), cfg=None, workspace=None)

    for width in (42, 50, 59, 60, 72, 79, 80, 120):
        banner = build_startup_banner(rt, width=width)
        assert all(cell_width(line) == width for line in banner.splitlines())
        assert banner.count("100%") == 6, f"W={width}\n{banner}"
        stats_section = banner.split("── BASE STATS", 1)[1]
        if width < 72:
            assert " │  " not in stats_section
        else:
            assert " │  " in stats_section


def test_startup_uses_canonical_skill_xp_projection_and_limits_to_five(monkeypatch) -> None:
    stats = {name: {"progress": 0} for name in ("clarity", "precision", "efficiency", "endurance", "mastery")}
    skills = [SimpleNamespace(name=f"legacy-{index}", domain="legacy") for index in range(6)]
    rows = tuple(
        SkillXPProjectionRow(
            capability_id=f"cap-{index}",
            display_name=f"Skill {index}",
            total_xp=100 - index,
            level=2,
            tier="Apprentice",
            progress_percent=50,
            xp_into_level=50,
            xp_to_next_level=50,
            last_used_at=None,
        )
        for index in range(5)
    )
    monkeypatch.setattr("hund.stats.compute_all", lambda: stats)
    monkeypatch.setattr("hund.skills.vault.SkillVault.get_active_skills", lambda self, workspace=None: skills)
    monkeypatch.setattr("hund.skills.vault.SkillVault.get_core_skills", lambda self: [])
    monkeypatch.setattr("hund.ui.render.project_active_skill_xp", lambda value, **kwargs: rows, raising=False)

    banner = build_startup_banner(SimpleNamespace(profile=SimpleNamespace(), cfg=None, workspace=None), width=80)

    assert "ACTIVE SKILLS (" not in banner
    assert "Skill 0" in banner and "Skill 4" in banner
    assert "legacy-5" not in banner
    assert "L2" in banner


def test_startup_truncates_long_skill_names_before_the_shared_progress_column(monkeypatch) -> None:
    stats = {name: {"progress": 0} for name in ("clarity", "precision", "efficiency", "endurance", "mastery")}
    rows = (
        SkillXPProjectionRow("cap-1", "b2b-outreach-migration", 4, 1, "Novice", 50, 25, 25, None),
        SkillXPProjectionRow("cap-2", "kundsupport", 4, 1, "Novice", 50, 25, 25, None),
        SkillXPProjectionRow("cap-3", "marketing", 4, 1, "Novice", 50, 25, 25, None),
    )
    monkeypatch.setattr("hund.stats.compute_all", lambda: stats)
    monkeypatch.setattr("hund.skills.vault.SkillVault.get_active_skills", lambda self, workspace=None: [])
    monkeypatch.setattr("hund.skills.vault.SkillVault.get_core_skills", lambda self: [])
    monkeypatch.setattr("hund.ui.render.project_active_skill_xp", lambda value, **kwargs: rows)

    banner = build_startup_banner(SimpleNamespace(profile=SimpleNamespace(), cfg=None, workspace=None), width=80)
    skill_lines = [line for line in banner.splitlines() if "L1" in line]

    assert "b2b-outreach-migration" not in banner
    assert "…" in skill_lines[0]
    assert len({line.index("█████") for line in skill_lines}) == 1


def test_spec_labels_tokenization() -> None:
    spec_lines = [
        "║  OS      Windows 11 Pro                                                       ║",
        "║  HOST    razor                                                                ║",
        "║  CPU     Intel Core i7-8550U                                                  ║",
        "║  RAM     16.0 GB                                                              ║",
        "║  GPU     Intel UHD Graphics 620                                               ║",
        "║  MODEL   deepseek-v4-pro                                                      ║",
    ]
    for line in spec_lines:
        toks = _lex_banner_line(line)
        assert toks[0] == ("class:accent", "║")
        assert toks[-1] == ("class:accent", "║")
        meta_toks = [t for t in toks if t[0] == "class:meta_accent"]
        assert len(meta_toks) == 1, f"Missing meta_accent token in: {toks}"
        assert meta_toks[0][1] in ("OS", "HOST", "CPU", "RAM", "GPU", "MODEL")
        # Ensure value is styled with class:primary
        val_toks = [t for t in toks if t[0] == "class:primary"]
        assert len(val_toks) == 1
