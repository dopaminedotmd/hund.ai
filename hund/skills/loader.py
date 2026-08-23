"""Skill-loader — läs giltiga skills från brain/skills/ + paketerade builtins.

Lagringsformat v1: JSON-filer, en skill per fil (`<name>.json`). Paketet skeppar
inbyggda skills i `builtins/`; användare kan lägga egna i HundHome/brain/skills/
(fas 9.5 Del C) som skuggar builtins med samma namn.
"""
from __future__ import annotations

import json
from pathlib import Path

from .model import Skill
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
    """Ladda enbart inbyggda konstitutionella kärn-instinkter."""
    bdir = _builtins_dir()
    if not bdir.exists():
        return []
    skills = []
    for f in sorted(bdir.glob("*.json")):
        sk = _read_skill_file(f)
        if sk:
            skills.append(sk)
    return skills


def load_domain_skills(home: Path | None = None) -> list[Skill]:
    """Ladda användarens skapade/installerade domän-skills från HundHome/brain/skills/ och workspace."""
    by_name: dict[str, Skill] = {}

    # 1. Globala skills i HundHome/brain/skills/
    udir = skills_dir(home)
    if udir.exists():
        for f in sorted(udir.glob("*.json")):
            sk = _read_skill_file(f)
            if sk:
                by_name[sk.name] = sk

    # 2. Lokala skills i aktuellt workspace/brain/skills/ (om annat än home)
    ws_dir = Path.cwd() / "brain" / "skills"
    if ws_dir.exists() and ws_dir.resolve() != udir.resolve():
        for f in sorted(ws_dir.glob("*.json")):
            sk = _read_skill_file(f)
            if sk:
                by_name[sk.name] = sk

    return list(by_name.values())


def load_skills(home: Path | None = None) -> list[Skill]:
    """Alla giltiga skills: builtins + HundHome, namnunika (HundHome vinner)."""
    by_name: dict[str, Skill] = {}

    for sk in load_builtins():
        by_name[sk.name] = sk

    for sk in load_domain_skills(home):
        by_name[sk.name] = sk

    return list(by_name.values())


def get_skill(name: str, home: Path | None = None) -> Skill | None:
    return next((s for s in load_skills(home) if s.name == name), None)


def load_file(path: Path) -> tuple[Skill | None, list[str]]:
    """Ladda + validera en specifik fil (för `skills validate`/`add`)."""
    try:
        skill = Skill.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        return None, [f"ogiltig JSON/struktur: {e}"]
    return skill, validate(skill)


def add_skill(path: Path, home: Path | None = None) -> tuple[Skill | None, list[str]]:
    """Kopiera en giltig skill-fil till brain/skills/. Return (skill, errors)."""
    skill, errors = load_file(path)
    if errors or skill is None:
        return None, errors
    target_dir = skills_dir(home)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / f"{skill.name}.json").write_text(
        json.dumps(skill.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return skill, []
