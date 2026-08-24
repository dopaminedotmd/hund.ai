"""Memory package facade — persistent, evidence-weighted, context-gated user and project memory.

Canonical storage in memory.db (SQLite) with an atomic materialized view in user.md.
Provides backward compatibility for existing callers (ensure_seed, inject, update_user, etc.).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ..doctor import EnvironmentProfile
from .db import connect_memory
from .engine import (
    apply_correction,
    forget_memory,
    get_audit_history,
    get_memory,
    list_active_memories,
    list_conflicts,
    record_contradiction,
    record_memory,
    reinforce_memory,
)
from .gating import select_memory_bullets
from .models import (
    CATEGORY_BIOGRAPHICAL_FACT,
    CATEGORY_CORE,
    CATEGORY_PROJECT_STATE,
    CATEGORY_STABLE_PREFERENCE,
    CATEGORY_TEMPORARY_CONTEXT,
    CATEGORY_WORKFLOW_HABIT,
    CATEGORY_WORKING_PREFERENCE,
    MemoryAuditEntry,
    MemoryItem,
    SCOPE_USER_GLOBAL,
    STATUS_DRAFT,
    STATUS_FLAGGED,
    STATUS_FORGOTTEN,
    STATUS_SUPERSEDED,
    STATUS_VERIFIED,
)
from .view import USER_MD_SEED, render_user_md, sync_user_md


def _home() -> Path:
    from ..paths import hund_home

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
    """Create user.md if missing. Idempotent — never overwrites existing."""
    p = user_path(home)
    if not p.exists():
        p.write_text(USER_MD_SEED, encoding="utf-8")


def _bullets(path: Path) -> list[str]:
    """Read lines starting with '- ' (stripped prefix). Skips comments (#) and empty."""
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
    """Memory lines to inject into system prompt (context-gated from memory.db or user.md)."""
    return select_memory_bullets(home=home)


def update_user(text: str, home: Optional[Path] = None) -> Path:
    """Write user.md and sync entries into canonical memory.db as verified items."""
    p = user_path(home)
    header = USER_MD_SEED.splitlines()[0] + "\n"
    p.write_text(header + text.rstrip() + "\n", encoding="utf-8")

    # Sync parsed bullets into memory.db
    db_file = _dir(home) / "memory.db"
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- "):
            stmt = s[2:].strip()
            if stmt:
                try:
                    record_memory(
                        statement=stmt,
                        scope=SCOPE_USER_GLOBAL,
                        category=CATEGORY_STABLE_PREFERENCE,
                        source_type="user",
                        is_core=False,
                        db_path=db_file,
                    )
                except Exception:
                    pass

    return p


def refresh_env(
    profile: EnvironmentProfile,
    home: Optional[Path] = None,
    *,
    force: bool = False,
) -> Optional[Path]:
    """Write environment.md from doctor profile."""
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
    """Formatted view for CLI: user.md + environment.md + active database memory summary."""
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
