"""Fas 9.5 Del A — memory store + prompt-injektion.

Verifierar: seed (idempotent), bullet-parsning, update_user, refresh_env
(force/skip), prompt-sektion (efter persona, före miljö) och att tom user.md
inte injicerar en sektion.
"""
from __future__ import annotations

from hund_cli import memory as M
from hund_cli.agent.prompt_builder import build_system_prompt
from hund_cli.doctor import EnvironmentProfile


def _prof(**kw) -> EnvironmentProfile:
    base = dict(
        os="Windows",
        os_caption="Microsoft Windows 11 Pro",
        os_arch="64-bit",
        cpu_count=8,
        processor="CPU-X",
        hostname="WS1",
        total_ram_gb=16.0,
        shell="pwsh",
    )
    base.update(kw)
    return EnvironmentProfile(**base)


def test_ensure_seed_creates_user_md(tmp_path):
    M.ensure_seed(home=tmp_path)
    assert (tmp_path / "memory" / "user.md").exists()


def test_ensure_seed_idempotent_no_overwrite(tmp_path):
    p = tmp_path / "memory" / "user.md"
    p.parent.mkdir(parents=True)
    p.write_text("# custom\n- foo\n", encoding="utf-8")
    M.ensure_seed(home=tmp_path)
    assert "custom" in p.read_text(encoding="utf-8")


def test_inject_empty_when_seeded_only(tmp_path):
    M.ensure_seed(home=tmp_path)
    assert M.inject(home=tmp_path) == []


def test_update_user_then_inject(tmp_path):
    M.update_user("- föredrar svenska\n- korta svar", home=tmp_path)
    assert M.inject(home=tmp_path) == ["föredrar svenska", "korta svar"]


def test_refresh_env_writes_snapshot(tmp_path):
    p = M.refresh_env(_prof(hostname="WS1", total_ram_gb=16.0), home=tmp_path)
    assert p and p.exists()
    txt = p.read_text(encoding="utf-8")
    assert "WS1" in txt
    assert "16.0GB" in txt
    assert "Microsoft Windows 11 Pro" in txt


def test_refresh_env_skips_existing_unless_force(tmp_path):
    M.refresh_env(_prof(hostname="A"), home=tmp_path)
    M.refresh_env(_prof(hostname="B"), home=tmp_path)  # ingen force
    assert "A" in M.env_path(home=tmp_path).read_text(encoding="utf-8")
    M.refresh_env(_prof(hostname="C"), home=tmp_path, force=True)
    assert "C" in M.env_path(home=tmp_path).read_text(encoding="utf-8")


def test_memory_section_in_prompt(tmp_path):
    M.update_user("- regel X", home=tmp_path)
    prompt = build_system_prompt("PERSONA", _prof(), memory_lines=M.inject(home=tmp_path))
    assert "## Persistent minne" in prompt
    assert "regel X" in prompt


def test_memory_after_persona_before_env(tmp_path):
    M.update_user("- minnesrad", home=tmp_path)
    prompt = build_system_prompt("PERSONA", _prof(), memory_lines=M.inject(home=tmp_path))
    i_mem = prompt.index("## Persistent minne")
    i_env = prompt.index("## Din miljö")
    assert 0 < i_mem < i_env


def test_no_memory_section_when_empty(tmp_path):
    M.ensure_seed(home=tmp_path)
    prompt = build_system_prompt("P", _prof(), memory_lines=M.inject(home=tmp_path))
    assert "## Persistent minne" not in prompt


def test_show_returns_both_files(tmp_path):
    M.update_user("- foo", home=tmp_path)
    M.refresh_env(_prof(hostname="HOSTX"), home=tmp_path)
    out = M.show(home=tmp_path)
    assert "user.md" in out
    assert "environment.md" in out
    assert "HOSTX" in out
