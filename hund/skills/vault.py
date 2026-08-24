"""Skill Vault — manages active capacity (max 6 slots) vs vaulted domain skills.

Persists active and vaulted domain skill states to HundHome/brain/skill_state.json.
Constitutional builtins (12 core instincts) are always active in background
and never consume domain inventory slots.
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Optional

from .loader import load_builtins, load_domain_skills, load_skills
from .model import MAX_ACTIVE_SKILLS, Skill

# Default domain skills active on fresh install
DEFAULT_ACTIVE_SKILLS: list[str] = []

# Legacy security skills (kept as constant for safety compatibility)
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
        domain_skills = load_domain_skills(self.home)
        domain_names = [s.name for s in domain_skills]
        equippable = {
            s.name for s in domain_skills if s.lifecycle_state in {"active", "proven"}
        }
        raw = self._load_raw_state()

        # Clean legacy builtins from state file if present
        active = [name for name in raw.get("active", []) if name in domain_names]
        vaulted = [name for name in raw.get("vaulted", []) if name in domain_names]

        # Categorize any newly added domain skills
        for name in domain_names:
            if name not in active and name not in vaulted:
                if name in equippable and len(active) < self.max_active:
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

    def get_core_skills(self) -> list[Skill]:
        """Return the 11 constitutional core instincts."""
        return load_builtins()

    def get_domain_skills(self) -> list[Skill]:
        """Return all user/domain skills mapped with active vs vaulted status."""
        domain_skills = load_domain_skills(self.home)
        raw = self._load_raw_state()
        active_set = set(raw.get("active", []))

        result = []
        for s in domain_skills:
            if s.name in active_set:
                result.append(replace(s, vault_state="equipped"))
            else:
                result.append(replace(s, vault_state="vaulted"))
        return result

    def get_all_skills(self) -> list[Skill]:
        """Return domain skills with status mapped."""
        return self.get_domain_skills()

    def get_active_skills(self) -> list[Skill]:
        """Return active domain skills (0/6 on fresh install)."""
        return [s for s in self.get_domain_skills() if s.vault_state == "equipped"]

    def list_vaulted(self) -> list[Skill]:
        """Return vaulted domain skills."""
        return [s for s in self.get_domain_skills() if s.vault_state == "vaulted"]

    def equip(self, name: str) -> tuple[bool, str]:
        raw = self._load_raw_state()
        active = raw.get("active", [])
        vaulted = raw.get("vaulted", [])
        all_names = set(active) | set(vaulted)

        if name not in all_names:
            return False, f"Domain skill '{name}' not found in vault."

        if name in active:
            return False, f"Domain skill '{name}' is already equipped ({len(active)}/{self.max_active} active)."

        skill = next((s for s in load_domain_skills(self.home) if s.name == name), None)
        if skill is None or skill.lifecycle_state not in {"active", "proven"}:
            return False, f"Domain skill '{name}' is not active/proven and cannot be equipped."

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
            return False, f"Domain skill '{name}' not found."

        if name in vaulted:
            return False, f"Domain skill '{name}' is already in the vault."

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
            return False, f"Domain skill '{old_name}' is not currently equipped."

        if new_name not in vaulted:
            if new_name in active:
                return False, f"Domain skill '{new_name}' is already equipped."
            return False, f"Domain skill '{new_name}' not found in vault."
        skill = next((s for s in load_domain_skills(self.home) if s.name == new_name), None)
        if skill is None or skill.lifecycle_state not in {"active", "proven"}:
            return False, f"Domain skill '{new_name}' is not active/proven and cannot be equipped."

        active.remove(old_name)
        vaulted.remove(new_name)

        active.append(new_name)
        vaulted.append(old_name)

        self._save_raw_state({"active": active, "vaulted": vaulted})
        return True, f"Swapped '{old_name}' for '{new_name}'."
