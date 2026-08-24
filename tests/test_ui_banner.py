"""Unit tests for the fullscreen startup banner per TUI_FACIT.md §4."""
from types import SimpleNamespace
from hund.ui.render import build_startup_banner
from hund.ui.fullscreen import _lex_banner_line, _OutputLexer
from prompt_toolkit.document import Document


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
    assert "── BASE ATTRIBUTES ──" in banner
    assert "── SKILLS" in banner
    assert "CLR Clarity" in banner
    assert "PRC Precision" in banner
    assert "EFF Efficiency" in banner
    assert "END Endurance" in banner
    assert "MAS Mastery" in banner
    assert "commands: /skills · /stats · /theme · /model · /clear · /exit" in banner


def test_banner_lexer_tokenization() -> None:
    top_line = "╔══════════════════════════════════════════════════════════════════════════════╗"
    logo_line = "║  ████▄ ██ ██ ████▄ ▄████                                                     ║"
    header_line = "║  ── BASE ATTRIBUTES ──               │  ── SKILLS (6/6) ──                   ║"
    stat_line = "║  CLR Clarity    ████████░░ 72%       │  code-surgeon       ████████░░ 74%    ║"
    cmd_line = "║  commands: /skills · /stats · /theme · /model · /clear · /exit               ║"
    bot_line = "╚══════════════════════════════════════════════════════════════════════════════╝"

    toks_top = _lex_banner_line(top_line)
    assert toks_top[0][0] == "class:accent"

    toks_logo = _lex_banner_line(logo_line)
    assert any(t[0] == "class:logo" and "████▄" in t[1] for t in toks_logo)

    toks_hdr = _lex_banner_line(header_line)
    assert any(t[0] == "class:header" and "BASE ATTRIBUTES" in t[1] for t in toks_hdr)
    assert any(t[0] == "class:secondary" and "│" in t[1] for t in toks_hdr)

    toks_stat = _lex_banner_line(stat_line)
    assert any(t[0] == "class:accent bold" and "CLR" in t[1] for t in toks_stat)
    assert any(t[0] == "class:learning" and "██" in t[1] for t in toks_stat)
    assert any(t[0] == "class:primary" and "code-surgeon" in t[1] for t in toks_stat)

    toks_cmd = _lex_banner_line(cmd_line)
    assert any(t[0] == "class:secondary" and "commands:" in t[1] for t in toks_cmd)

    toks_bot = _lex_banner_line(bot_line)
    assert toks_bot[0][0] == "class:accent"


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

    for test_w in (50, 60, 72, 80, 100):
        banner = build_startup_banner(mock_rt, width=test_w)
        lines = banner.splitlines()
        for i, line in enumerate(lines):
            assert len(line) == test_w, f"W={test_w}, line {i}: {len(line)} != {test_w}"

