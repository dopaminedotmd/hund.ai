"""Skill Vault — manages active capacity (max 6 slots) vs vaulted skills.

Persists active and vaulted skill states to HundHome/brain/skill_state.json.
Only active skills are returned for prompt injection and trigger matching.
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Optional

from .loader import load_skills
from .model import MAX_ACTIVE_SKILLS, Skill

# Mandatory baseline security skills that must remain active by default
DEFAULT_ACTIVE_SKILLS = [
    "shell-command-safety",
    "file-operations",
    "git-safety",
    "external-content-safety",
    "systematic-debugging",
    "environment-profiling",
]

# Security skills that cannot be parked without explicit force override
MANDATORY_SECURITY_SKILLS = frozenset({
    "shell-command-safety",
    "file-operations",
    "git-safety",
    "external-content-safety",
})


class SkillVault:
    def __init__(self, home: Optional[Path] = None, max_active: Optional[int] = None) -> None:
        self.home = home
        self.max_active = max_active or int(
            os.environ.get("HUND_MAX_ACTIVE_SKILLS", str(MAX_ACTIVE_SKILLS))
        )
        self._state_file = self._resolve_state_path()
        self._sync_state()

    def _resolve_state_path(self) -> Path:
        if self.home is not None:
            base = self.home
        else:
            from ..paths import hund_home
            base = hund_home()
        brain_dir = base / "brain"
        brain_dir.mkdir(parents=True, exist_ok=True)
        return brain_dir / "skill_state.json"

    def _load_raw_state(self) -> dict[str, list[str]]:
        if self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {
                        "active": list(data.get("active", [])),
                        "vaulted": list(data.get("vaulted", [])),
                    }
            except Exception:
                pass
        return {}

    def _save_raw_state(self, state: dict[str, list[str]]) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def _sync_state(self) -> None:
        all_skills = load_skills(self.home)
        all_names = [s.name for s in all_skills]
        raw = self._load_raw_state()

        if not raw:
            # First initialization: 6 default active skills, rest vaulted
            active = [name for name in DEFAULT_ACTIVE_SKILLS if name in all_names][:self.max_active]
            vaulted = [name for name in all_names if name not in active]
            raw = {"active": active, "vaulted": vaulted}
            self._save_raw_state(raw)
            return

        active = [name for name in raw.get("active", []) if name in all_names]
        vaulted = [name for name in raw.get("vaulted", []) if name in all_names]

        # Categorize any newly added skills
        for name in all_names:
            if name not in active and name not in vaulted:
                if len(active) < self.max_active:
                    active.append(name)
                else:
                    vaulted.append(name)

        # Enforce max active cap
        while len(active) > self.max_active:
            overflow = active.pop()
            if overflow not in vaulted:
                vaulted.append(overflow)

        raw = {"active": active, "vaulted": vaulted}
        self._save_raw_state(raw)

    def get_all_skills(self) -> list[Skill]:
        """Return all skills with status mapped to active vs vaulted."""
        all_skills = load_skills(self.home)
        raw = self._load_raw_state()
        active_set = set(raw.get("active", []))

        result = []
        for s in all_skills:
            if s.name in active_set:
                result.append(replace(s, status="active"))
            else:
                result.append(replace(s, status="vaulted"))
        return result

    def get_active_skills(self) -> list[Skill]:
        return [s for s in self.get_all_skills() if s.status == "active"]

    def list_vaulted(self) -> list[Skill]:
        return [s for s in self.get_all_skills() if s.status == "vaulted"]

    def equip(self, name: str) -> tuple[bool, str]:
        raw = self._load_raw_state()
        active = raw.get("active", [])
        vaulted = raw.get("vaulted", [])
        all_names = set(active) | set(vaulted)

        if name not in all_names:
            return False, f"Skill '{name}' not found."

        if name in active:
            return False, f"Skill '{name}' is already equipped ({len(active)}/{self.max_active} active)."

        if len(active) >= self.max_active:
            return False, f"Active skill capacity reached ({len(active)}/{self.max_active}). Park or swap a skill first."

        if name in vaulted:
            vaulted.remove(name)
        active.append(name)

        self._save_raw_state({"active": active, "vaulted": vaulted})
        return True, f"Equipped '{name}'. ({len(active)}/{self.max_active} slots active)"

    def park(self, name: str, *, force: bool = False) -> tuple[bool, str]:
        raw = self._load_raw_state()
        active = raw.get("active", [])
        vaulted = raw.get("vaulted", [])
        all_names = set(active) | set(vaulted)

        if name not in all_names:
            return False, f"Skill '{name}' not found."

        if name in vaulted:
            return False, f"Skill '{name}' is already in the vault."

        if name in MANDATORY_SECURITY_SKILLS and not force:
            return False, f"Security skill '{name}' cannot be parked (mandatory runtime invariant)."

        active.remove(name)
        if name not in vaulted:
            vaulted.append(name)

        self._save_raw_state({"active": active, "vaulted": vaulted})
        return True, f"Parked '{name}' into vault. ({len(active)}/{self.max_active} slots active)"

    def swap(self, old_name: str, new_name: str) -> tuple[bool, str]:
        raw = self._load_raw_state()
        active = raw.get("active", [])
        vaulted = raw.get("vaulted", [])

        if old_name not in active:
            return False, f"Skill '{old_name}' is not currently equipped."

        if new_name not in vaulted:
            if new_name in active:
                return False, f"Skill '{new_name}' is already equipped."
            return False, f"Skill '{new_name}' not found in vault."

        if old_name in MANDATORY_SECURITY_SKILLS:
            return False, f"Security skill '{old_name}' cannot be parked (mandatory runtime invariant)."

        active.remove(old_name)
        vaulted.remove(new_name)

        active.append(new_name)
        vaulted.append(old_name)

        self._save_raw_state({"active": active, "vaulted": vaulted})
        return True, f"Swapped '{old_name}' for '{new_name}'."
