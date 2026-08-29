"""Skill Vault — manages active capacity (max 6 slots) vs vaulted domain skills with scoped state schema v2.

Persists active and vaulted domain skill states to HundHome/brain/skill_state.json.
Constitutional builtins (12 core instincts) are always active in background
and never consume domain inventory slots.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any, Optional
import uuid

from .loader import (
    load_builtins,
    load_domain_skills,
    load_domain_skills_for_scope_key,
    load_skills,
    skills_dir,
)
from .model import MAX_ACTIVE_SKILLS, Skill
from .scope import ScopedSkillId, compute_workspace_key

# Default domain skills active on fresh install
DEFAULT_ACTIVE_SKILLS: list[str] = []

# Legacy security skills (kept as constant for safety compatibility)
MANDATORY_SECURITY_SKILLS = frozenset({
    "shell-command-safety",
    "file-operations",
    "git-safety",
    "external-content-safety",
})


def _fsync_replace(src: Path, dst: Path, max_retries: int = 5) -> None:
    """Atomic file replacement with Windows retry backoff."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(max_retries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == max_retries - 1:
                raise
            time.sleep(0.05 * (2 ** attempt))


class SkillVault:
    def __init__(self, home: Optional[Path] = None, max_active: Optional[int] = None) -> None:
        self.home = home
        self.max_active = max_active or int(
            os.environ.get("HUND_MAX_ACTIVE_SKILLS", str(MAX_ACTIVE_SKILLS))
        )
        self._state_file = self._resolve_state_path()
        self._migrate_and_sync()

    def _resolve_state_path(self) -> Path:
        if self.home is not None:
            base = self.home
        else:
            from ..paths import hund_home
            base = hund_home()
        brain_dir = base / "brain"
        brain_dir.mkdir(parents=True, exist_ok=True)
        return brain_dir / "skill_state.json"

    def _backup_file(self, prefix: str) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        hdir = skills_dir(self.home) / ".history"
        hdir.mkdir(parents=True, exist_ok=True)
        backup_path = hdir / f"{prefix}_{ts}.json"
        if self._state_file.exists():
            try:
                shutil.copy2(self._state_file, backup_path)
            except Exception:
                pass
        return backup_path

    def _load_raw_state(self) -> dict[str, Any]:
        if not self._state_file.exists():
            return {"schema_version": 2, "entries": []}
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            # Corrupt state file recovery
            self._backup_file("skill_state_corrupt")
            recovered = self._recover_corrupt_state()
            self._save_raw_state(recovered)
            return recovered
        return {"schema_version": 2, "entries": []}

    def _recover_corrupt_state(self) -> dict[str, Any]:
        domain_skills = load_domain_skills(self.home)
        entries = []
        equipped_count = 0
        for s in domain_skills:
            vault_state = "vaulted"
            if s.lifecycle_state in ("active", "proven") and equipped_count < self.max_active:
                vault_state = "equipped"
                equipped_count += 1
            entries.append({
                "scope_key": s.scope if s.scope != "project" else "global",
                "capability_id": s.capability_id or f"{s.domain}/{s.name}",
                "name": s.name,
                "vault_state": vault_state,
                "pinned": False,
            })
        return {"schema_version": 2, "entries": entries}

    def _save_raw_state(self, state: dict[str, Any]) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_file.with_suffix(f".tmp.{os.getpid()}_{uuid.uuid4().hex[:8]}")
        try:
            content = json.dumps(state, indent=2, ensure_ascii=False)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            _fsync_replace(tmp, self._state_file)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass

    def _migrate_and_sync(self) -> None:
        if not self._state_file.exists():
            domain_skills = load_domain_skills(self.home)
            if domain_skills:
                initial_state = self._recover_corrupt_state()
                self._save_raw_state(initial_state)
            else:
                self._save_raw_state({"schema_version": 2, "entries": []})
            return

        raw = self._load_raw_state()
        if raw.get("schema_version") == 2:
            return  # Strict no-op for already migrated schema

        # Migration from legacy v1 {"active": [...], "vaulted": [...]}
        self._backup_file("skill_state_v1_backup")
        domain_skills = load_domain_skills(self.home)
        skills_by_name = {s.name: s for s in domain_skills}

        active_names = list(raw.get("active", []))
        vaulted_names = list(raw.get("vaulted", []))

        # Check for duplicates across active & vaulted -> fail closed to vaulted
        conflicted_names = set(active_names) & set(vaulted_names)
        for name in conflicted_names:
            while name in active_names:
                active_names.remove(name)

        entries: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        seen_identities: set[tuple[str, str, str]] = set()

        all_names = list(dict.fromkeys(active_names + vaulted_names))
        for name in all_names:
            skill = skills_by_name.get(name)
            if skill is None:
                unresolved.append({
                    "name": name,
                    "former_disposition": "equipped" if name in active_names else "vaulted",
                    "reason": "Canonical skill file not found in brain/skills/ storage",
                })
                continue

            cap_id = skill.capability_id or f"{skill.domain}/{skill.name}"
            scope_key = "global"
            ident = (scope_key, cap_id, skill.name)

            if ident in seen_identities:
                unresolved.append({
                    "name": name,
                    "former_disposition": "vaulted",
                    "reason": "Duplicate scoped identity collision during migration",
                })
                continue
            seen_identities.add(ident)

            is_active = (name in active_names) and (name not in conflicted_names)
            vault_state = "equipped" if is_active and skill.lifecycle_state in ("active", "proven") else "vaulted"

            entries.append({
                "scope_key": scope_key,
                "capability_id": cap_id,
                "name": skill.name,
                "vault_state": vault_state,
                "pinned": skill.user_pinned,
            })

        if unresolved:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            unres_path = skills_dir(self.home) / ".history" / f"skill_state_v1_unresolved_{ts}.json"
            unres_path.parent.mkdir(parents=True, exist_ok=True)
            unres_path.write_text(json.dumps(unresolved, indent=2, ensure_ascii=False), encoding="utf-8")

        new_state = {"schema_version": 2, "entries": entries}
        self._save_raw_state(new_state)

    def sync_scoped_state(
        self,
        skills: list[Skill],
        workspace_key: str = "global",
        desired_equip: str | None = None,
    ) -> None:
        """Sync vault entries against newly loaded skills and desired disposition."""
        raw = self._load_raw_state()
        entries = list(raw.get("entries", []))
        entries_by_key = {
            (e.get("scope_key", "global"), e.get("capability_id", ""), e.get("name", "")): e
            for e in entries
        }

        for s in skills:
            s_scope = s.scope if s.scope != "project" else workspace_key
            s_cap = s.capability_id or f"{s.domain}/{s.name}"
            key = (s_scope, s_cap, s.name)
            if key not in entries_by_key:
                vault_state = "equipped" if (desired_equip == s.name and s.lifecycle_state in ("active", "proven")) else "vaulted"
                new_entry = {
                    "scope_key": s_scope,
                    "capability_id": s_cap,
                    "name": s.name,
                    "vault_state": vault_state,
                    "pinned": s.user_pinned,
                }
                entries.append(new_entry)
                entries_by_key[key] = new_entry

        # Enforce max active capacity per scope without evicting pinned skills
        equipped_entries = [e for e in entries if e.get("vault_state") == "equipped" and e.get("scope_key") == workspace_key]
        if len(equipped_entries) > self.max_active:
            # Demote unpinned first
            for e in reversed(equipped_entries):
                if not e.get("pinned", False) and len(equipped_entries) > self.max_active:
                    e["vault_state"] = "vaulted"
                    equipped_entries.remove(e)

        self._save_raw_state({"schema_version": 2, "entries": entries})

    def get_core_skills(self) -> list[Skill]:
        """Return the 12 constitutional core instincts."""
        return load_builtins()

    def get_domain_skills(
        self,
        *,
        workspace: Path | str | None = None,
        workspace_key: str | None = None,
    ) -> list[Skill]:
        """Return all user/domain skills mapped with active vs vaulted status."""
        if workspace is not None and workspace_key is not None:
            raise ValueError("Pass either workspace or workspace_key, not both")
        if workspace_key is None:
            workspace_key = compute_workspace_key(workspace)
            domain_skills = load_domain_skills(self.home, workspace=workspace)
        else:
            domain_skills = load_domain_skills_for_scope_key(
                self.home, workspace_key=workspace_key
            )
        raw = self._load_raw_state()
        entries = raw.get("entries", [])
        entry_map = {
            (
                e.get("scope_key", "global"),
                e.get("capability_id", ""),
                e.get("name", ""),
            ): e.get("vault_state", "vaulted")
            for e in entries
        }

        result = []
        for s in domain_skills:
            scope_key = workspace_key if s.scope == "project" else "global"
            capability_id = s.capability_id or f"{s.domain}/{s.name}"
            v_state = entry_map.get(
                (scope_key, capability_id, s.name), "vaulted"
            )
            result.append(replace(s, vault_state=v_state))
        return result

    def get_all_skills(
        self,
        *,
        workspace: Path | str | None = None,
        workspace_key: str | None = None,
    ) -> list[Skill]:
        return self.get_domain_skills(
            workspace=workspace, workspace_key=workspace_key
        )

    def get_active_skills(
        self,
        *,
        workspace: Path | str | None = None,
        workspace_key: str | None = None,
    ) -> list[Skill]:
        return [
            s
            for s in self.get_domain_skills(
                workspace=workspace, workspace_key=workspace_key
            )
            if s.vault_state == "equipped"
        ]

    def list_vaulted(
        self,
        *,
        workspace: Path | str | None = None,
        workspace_key: str | None = None,
    ) -> list[Skill]:
        return [
            s
            for s in self.get_domain_skills(
                workspace=workspace, workspace_key=workspace_key
            )
            if s.vault_state == "vaulted"
        ]

    def equip(
        self,
        scope_key_or_name: str | ScopedSkillId,
        capability_id: str | None = None,
        name: str | None = None,
    ) -> tuple[bool, str]:
        raw = self._load_raw_state()
        entries = list(raw.get("entries", []))

        if isinstance(scope_key_or_name, ScopedSkillId):
            scope_key = scope_key_or_name.scope_key
            target_capability_id = scope_key_or_name.capability_id
            target_name = scope_key_or_name.name
        elif name is not None:
            scope_key = scope_key_or_name
            target_capability_id = capability_id or ""
            target_name = name
        else:
            # Fallback legacy signature equip(name)
            scope_key = "global"
            target_capability_id = capability_id or ""
            target_name = scope_key_or_name

        matched_entry = next(
            (
                e
                for e in entries
                if e.get("name") == target_name
                and e.get("scope_key", "global") == scope_key
                and (
                    not target_capability_id
                    or e.get("capability_id", "") == target_capability_id
                )
            ),
            None,
        )
        if matched_entry is None:
            # Check if skill exists in domain storage
            skills = load_domain_skills_for_scope_key(
                self.home, workspace_key=scope_key
            )
            skill = next((s for s in skills if s.name == target_name), None)
            if skill is None:
                return False, f"Domain skill '{target_name}' not found in vault."
            matched_entry = {
                "scope_key": scope_key,
                "capability_id": skill.capability_id or f"{skill.domain}/{skill.name}",
                "name": skill.name,
                "vault_state": "vaulted",
                "pinned": skill.user_pinned,
            }
            entries.append(matched_entry)

        if matched_entry.get("vault_state") == "equipped":
            active_count = sum(
                1
                for e in entries
                if e.get("vault_state") == "equipped"
                and e.get("scope_key", "global") == scope_key
            )
            return False, f"Domain skill '{target_name}' is already equipped ({active_count}/{self.max_active} active)."

        active_count = sum(
            1
            for e in entries
            if e.get("vault_state") == "equipped"
            and e.get("scope_key", "global") == scope_key
        )
        if active_count >= self.max_active:
            return False, f"Active skill capacity reached ({active_count}/{self.max_active}). Park or swap a skill first."

        matched_entry["vault_state"] = "equipped"
        self._save_raw_state({"schema_version": 2, "entries": entries})
        new_active = sum(
            1
            for e in entries
            if e.get("vault_state") == "equipped"
            and e.get("scope_key", "global") == scope_key
        )
        return True, f"Equipped '{target_name}'. ({new_active}/{self.max_active} slots active)"

    def park(
        self,
        scope_key_or_name: str | ScopedSkillId,
        capability_id: str | None = None,
        name: str | None = None,
        *,
        force: bool = False,
    ) -> tuple[bool, str]:
        raw = self._load_raw_state()
        entries = list(raw.get("entries", []))

        if isinstance(scope_key_or_name, ScopedSkillId):
            scope_key = scope_key_or_name.scope_key
            target_capability_id = scope_key_or_name.capability_id
            target_name = scope_key_or_name.name
        elif name is not None:
            scope_key = scope_key_or_name
            target_capability_id = capability_id or ""
            target_name = name
        else:
            scope_key = "global"
            target_capability_id = capability_id or ""
            target_name = scope_key_or_name

        matched_entry = next(
            (
                e
                for e in entries
                if e.get("name") == target_name
                and e.get("scope_key", "global") == scope_key
                and (
                    not target_capability_id
                    or e.get("capability_id", "") == target_capability_id
                )
            ),
            None,
        )
        if matched_entry is None:
            return False, f"Domain skill '{target_name}' not found."

        if matched_entry.get("vault_state") == "vaulted":
            return False, f"Domain skill '{target_name}' is already in the vault."

        if matched_entry.get("pinned", False) and not force:
            return False, f"Domain skill '{target_name}' is user-pinned. Unpin before parking."

        matched_entry["vault_state"] = "vaulted"
        self._save_raw_state({"schema_version": 2, "entries": entries})
        active_count = sum(
            1
            for e in entries
            if e.get("vault_state") == "equipped"
            and e.get("scope_key", "global") == scope_key
        )
        return True, f"Parked '{target_name}' into vault. ({active_count}/{self.max_active} slots active)"

    def swap(
        self,
        old_item: str | ScopedSkillId,
        new_item: str | ScopedSkillId,
    ) -> tuple[bool, str]:
        old_name = old_item.name if isinstance(old_item, ScopedSkillId) else old_item
        new_name = new_item.name if isinstance(new_item, ScopedSkillId) else new_item
        old_scope = old_item.scope_key if isinstance(old_item, ScopedSkillId) else "global"
        new_scope = new_item.scope_key if isinstance(new_item, ScopedSkillId) else "global"

        raw = self._load_raw_state()
        entries = list(raw.get("entries", []))

        old_entry = next((e for e in entries if e.get("name") == old_name), None)
        new_entry = next((e for e in entries if e.get("name") == new_name), None)

        if old_entry is None or old_entry.get("vault_state") != "equipped":
            return False, f"Domain skill '{old_name}' is not currently equipped."

        if new_entry is None:
            # Check domain skills
            skills = load_domain_skills(self.home, workspace=new_scope)
            skill = next((s for s in skills if s.name == new_name), None)
            if skill is None or skill.lifecycle_state not in ("active", "proven"):
                return False, f"Domain skill '{new_name}' not found in vault or not active."
            new_entry = {
                "scope_key": new_scope,
                "capability_id": skill.capability_id or f"{skill.domain}/{skill.name}",
                "name": skill.name,
                "vault_state": "vaulted",
                "pinned": skill.user_pinned,
            }
            entries.append(new_entry)

        if new_entry.get("vault_state") == "equipped":
            return False, f"Domain skill '{new_name}' is already equipped."

        old_entry["vault_state"] = "vaulted"
        new_entry["vault_state"] = "equipped"
        self._save_raw_state({"schema_version": 2, "entries": entries})
        return True, f"Swapped '{old_name}' for '{new_name}'."

    def find_skill(
        self,
        name: str,
        *,
        workspace: Path | str | None = None,
        workspace_key: str | None = None,
    ) -> Skill | None:
        """Find a skill by name in active, vaulted or constitutional skills."""
        domain_skills = self.get_domain_skills(workspace=workspace, workspace_key=workspace_key)
        for s in domain_skills:
            if s.name == name or s.capability_id == name:
                return s
        for b in self.get_core_skills():
            if b.name == name:
                return b
        return None

    def has_skill(
        self,
        name: str,
        *,
        workspace: Path | str | None = None,
        workspace_key: str | None = None,
    ) -> bool:
        """Canonical check for skill existence."""
        return self.find_skill(name, workspace=workspace, workspace_key=workspace_key) is not None


def skill_exists(
    name: str,
    home: Path | None = None,
    workspace: Path | str | None = None,
) -> bool:
    """Canonical check for whether a skill exists in the skill registry/vault."""
    vault = SkillVault(home=home)
    return vault.has_skill(name, workspace=workspace)
