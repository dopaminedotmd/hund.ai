"""Skill loader — reads valid skills from brain/skills/ + packaged builtins.

Supports builtins, global domain skills, and workspace-scoped project skills.
Reserved directories (.drafts/, .history/) are never loaded as active skills.
"""
from __future__ import annotations

import json
from pathlib import Path

from .model import Skill
from .scope import compute_workspace_key
from .validator import validate


def skills_dir(home: Path | None = None) -> Path:
    from ..paths import hund_home

    base = home if home is not None else hund_home()
    return base / "brain" / "skills"


def _builtins_dir() -> Path:
    return Path(__file__).parent / "builtins"


def _read_skill_file(path: Path) -> Skill | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        skill = Skill.from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    return skill if not validate(skill) else None


def load_builtins() -> list[Skill]:
    """Load only built-in constitutional core instincts."""
    bdir = _builtins_dir()
    if not bdir.exists():
        return []
    skills = []
    for f in sorted(bdir.glob("*.json")):
        sk = _read_skill_file(f)
        if sk:
            skills.append(sk)
    return skills


def load_domain_skills_for_scope_key(
    home: Path | None = None, *, workspace_key: str = "global"
) -> list[Skill]:
    """Load domain skills using an already-derived workspace scope key."""
    by_name: dict[str, Skill] = {}
    udir = skills_dir(home)

    if udir.exists():
        for f in sorted(udir.glob("*.json")):
            sk = _read_skill_file(f)
            if sk:
                by_name[sk.name] = sk

    if workspace_key != "global":
        pdir = udir / "projects" / workspace_key
        if pdir.exists():
            for f in sorted(pdir.glob("*.json")):
                sk = _read_skill_file(f)
                if sk:
                    by_name[sk.name] = sk

    return list(by_name.values())


def load_domain_skills(
    home: Path | None = None, workspace: Path | str | None = None
) -> list[Skill]:
    """Load user-created domain skills for a workspace filesystem path.

    Workspace project skills take precedence over global domain skills.
    Reserved directories (.drafts, .history) are excluded.
    """
    workspace_key = compute_workspace_key(workspace)
    return load_domain_skills_for_scope_key(home, workspace_key=workspace_key)


def load_skills(home: Path | None = None, workspace: Path | str | None = None) -> list[Skill]:
    """Load all valid skills: builtins + global + workspace-scoped domain skills."""
    by_name: dict[str, Skill] = {}

    for sk in load_builtins():
        by_name[sk.name] = sk

    for sk in load_domain_skills(home, workspace=workspace):
        by_name[sk.name] = sk

    return list(by_name.values())


def get_skill(name: str, home: Path | None = None, workspace: Path | str | None = None) -> Skill | None:
    """Get a specific skill with precedence: project -> global -> builtin."""
    # 1. Project precedence
    if workspace is not None:
        ws_key = compute_workspace_key(workspace)
        if ws_key != "global":
            pfile = skills_dir(home) / "projects" / ws_key / f"{name}.json"
            if pfile.exists():
                sk = _read_skill_file(pfile)
                if sk and sk.name == name:
                    return sk

    # 2. Global domain precedence
    gfile = skills_dir(home) / f"{name}.json"
    if gfile.exists():
        sk = _read_skill_file(gfile)
        if sk and sk.name == name:
            return sk

    # 3. Builtin fallback
    for s in load_builtins():
        if s.name == name:
            return s

    return None


def load_file(path: Path) -> tuple[Skill | None, list[str]]:
    """Load and validate a specific file."""
    try:
        skill = Skill.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        return None, [f"invalid JSON/structure: {e}"]
    return skill, validate(skill)


def add_skill(path: Path, home: Path | None = None) -> tuple[Skill | None, list[str]]:
    """Copy a valid skill file to brain/skills/. Return (skill, errors)."""
    skill, errors = load_file(path)
    if errors or skill is None:
        return None, errors
    target_dir = skills_dir(home)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / f"{skill.name}.json").write_text(
        json.dumps(skill.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return skill, []
