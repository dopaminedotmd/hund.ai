"""Memory — persistent användarminne mellan sessioner.

Lagras som markdown under HundHome/memory/ (INTE under brain/):
  - user.md        användarprofil (språk, preferenser, projekt) → injiceras i prompt
  - environment.md hårdvarusnapshot från doctor → CLI-inspektion, ej dubbelinjicerad

Injektion: user.md-bullets → systemprompt EFTER persona, FÖRE miljöprofil
(se agent/prompt_builder.build_system_prompt). environment.md dubblerar den levande
doctor-profilen som redan injiceras live → visas bara via `hund memory show`.

`home`-param tillåter testisolation (tmp-HundHome) — samma mönster som knowledge.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .doctor import EnvironmentProfile

USER_SEED = """\
# Användarprofil
# hund läser rader som börjar med '- ' som minne. Redigera fritt.
# kör: hund memory update user
"""


def _home() -> Path:
    from .paths import hund_home

    return hund_home()


def _dir(home: Optional[Path] = None) -> Path:
    base = home if home is not None else _home()
    d = base / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_path(home: Optional[Path] = None) -> Path:
    return _dir(home) / "user.md"


def env_path(home: Optional[Path] = None) -> Path:
    return _dir(home) / "environment.md"


def ensure_seed(home: Optional[Path] = None) -> None:
    """Skapa user.md om saknad. Idempotent — skriver ALDRIG över befintlig."""
    p = user_path(home)
    if not p.exists():
        p.write_text(USER_SEED, encoding="utf-8")


def _bullets(path: Path) -> list[str]:
    """Radera '- '-rader (strippat prefix). Hoppar kommentarer (#) och tomma."""
    if not path.exists():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("- "):
            out.append(s[2:].strip())
    return out


def user_bullets(home: Optional[Path] = None) -> list[str]:
    return _bullets(user_path(home))


def inject(home: Optional[Path] = None) -> list[str]:
    """Minnesrader att injicera i systemprompt (user.md-bullets). Tom = ingen sektion."""
    return user_bullets(home)


def update_user(text: str, home: Optional[Path] = None) -> Path:
    """Skriv user.md. Behåll header; text läggs till som bullets."""
    p = user_path(home)
    header = USER_SEED.splitlines()[0] + "\n"
    p.write_text(header + text.rstrip() + "\n", encoding="utf-8")
    return p


def refresh_env(
    profile: EnvironmentProfile,
    home: Optional[Path] = None,
    *,
    force: bool = False,
) -> Optional[Path]:
    """Skriv environment.md från doctor-profil. Skippar om finns och ej force."""
    p = env_path(home)
    if p.exists() and not force:
        return None
    lines = [
        "# Hårdvaruprofil",
        "# snapshot från hund doctor — uppdatera med: hund memory refresh-env",
        f"- OS: {profile.os_caption or f'{profile.os} {profile.os_version}'}"
        + (f" ({profile.os_arch})" if profile.os_arch else ""),
        f"- Hostname: {profile.hostname or 'okänd'}",
        f"- CPU: {profile.processor or 'okänd'} ({profile.cpu_count} kärnor)",
    ]
    if profile.gpu_model:
        gpu_line = f"- GPU: {profile.gpu_model}"
        if profile.gpu_vram_mb:
            gpu_line += f" ({profile.gpu_vram_gb:.1f}GB VRAM)"
        lines.append(gpu_line)
    if profile.total_ram_gb:
        lines.append(f"- RAM: {profile.total_ram_gb:.1f}GB")
    lines.append(f"- Shell: {profile.shell}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def show(home: Optional[Path] = None) -> str:
    """Formaterad vy för CLI: innehåll i user.md + environment.md."""
    parts: list[str] = []
    up = user_path(home)
    parts.append("[bold]user.md[/bold]")
    parts.append(up.read_text(encoding="utf-8", errors="replace").rstrip() if up.exists() else "(saknas)")
    ep = env_path(home)
    parts.append("")
    parts.append("[bold]environment.md[/bold]")
    if ep.exists():
        parts.append(ep.read_text(encoding="utf-8", errors="replace").rstrip())
    else:
        parts.append("(saknas — kör: hund memory refresh-env)")
    return "\n".join(parts)
