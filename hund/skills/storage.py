"""Scoped skill storage — atomic writes, snapshots, rollbacks, and phase-marked journal."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Optional
import uuid

from ..paths import hund_home
from .loader import _read_skill_file, skills_dir
from .model import Skill
from .publication import PublicationGateReport


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


def _compute_file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SkillStorage:
    """Manages atomic writing, draft staging, version snapshots, journals, and rollback."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = home
        self._skills_dir = skills_dir(home)

    def get_canonical_path(self, name: str, scope: str, workspace_key: str = "global") -> Path:
        if scope == "project" and workspace_key != "global":
            return self._skills_dir / "projects" / workspace_key / f"{name}.json"
        return self._skills_dir / f"{name}.json"

    def get_draft_path(self, name: str, workspace_key: str = "global") -> Path:
        return self._skills_dir / ".drafts" / workspace_key / f"{name}.json"

    def get_history_dir(self, workspace_key: str = "global") -> Path:
        return self._skills_dir / ".history" / workspace_key

    def save_staged_draft(
        self,
        skill: Skill,
        report: PublicationGateReport | None,
        workspace_key: str = "global",
    ) -> Path:
        """Atomically save a staged draft into .drafts/<workspace_key>/<name>.json."""
        target = self.get_draft_path(skill.name, workspace_key)
        target.parent.mkdir(parents=True, exist_ok=True)

        data = skill.to_dict()
        if report is not None:
            data["_publication_gate_report"] = {
                "passed": report.passed,
                "failure_reasons": list(report.failure_reasons),
                "checks": [{"check": c.check_name, "passed": c.passed, "error": c.error_message} for c in report.checks],
            }

        tmp = target.with_suffix(f".tmp.{os.getpid()}_{uuid.uuid4().hex[:8]}")
        try:
            content = json.dumps(data, ensure_ascii=False, indent=2)
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_replace(tmp, target)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
        return target

    def snapshot_prior_version(self, existing_skill: Skill, workspace_key: str = "global") -> Path:
        """Create a version history snapshot in .history/<workspace_key>/."""
        hdir = self.get_history_dir(workspace_key)
        hdir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target = hdir / f"{existing_skill.name}__v{existing_skill.version}__{ts}.json"

        tmp = target.with_suffix(f".tmp.{os.getpid()}_{uuid.uuid4().hex[:8]}")
        try:
            content = json.dumps(existing_skill.to_dict(), ensure_ascii=False, indent=2)
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_replace(tmp, target)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
        return target

    def write_canonical_atomic(self, skill: Skill, workspace_key: str = "global") -> Path:
        """Atomically write canonical skill file with fsync."""
        target = self.get_canonical_path(skill.name, skill.scope, workspace_key)
        target.parent.mkdir(parents=True, exist_ok=True)

        tmp = target.with_suffix(f".tmp.{os.getpid()}_{uuid.uuid4().hex[:8]}")
        try:
            content = json.dumps(skill.to_dict(), ensure_ascii=False, indent=2)
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_replace(tmp, target)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
        return target

    def rollback_skill(
        self,
        name: str,
        workspace_key: str = "global",
        target_version: str | None = None,
        scope: str = "global",
    ) -> tuple[bool, str, Skill | None]:
        """Roll back a skill to a prior version snapshot atomically."""
        hdir = self.get_history_dir(workspace_key)
        if not hdir.exists():
            return False, f"No history found for skill '{name}' in workspace '{workspace_key}'.", None

        # Find matching snapshots
        pattern = f"{name}__v*.json"
        candidates = sorted(hdir.glob(pattern), reverse=True)
        if not candidates:
            return False, f"No snapshots found for skill '{name}'.", None

        chosen_snapshot: Path | None = None
        if target_version:
            for c in candidates:
                if f"__v{target_version}__" in c.name:
                    chosen_snapshot = c
                    break
            if chosen_snapshot is None:
                return False, f"Snapshot for version '{target_version}' of skill '{name}' not found.", None
        else:
            chosen_snapshot = candidates[0]

        restored_skill = _read_skill_file(chosen_snapshot)
        if restored_skill is None:
            return False, f"Corrupt snapshot found at '{chosen_snapshot.name}'. Rollback aborted.", None

        # Snapshot current canonical before rollback
        canonical_path = self.get_canonical_path(name, scope, workspace_key)
        if canonical_path.exists():
            current_skill = _read_skill_file(canonical_path)
            if current_skill is not None:
                self.snapshot_prior_version(current_skill, workspace_key)

        # Atomically restore
        self.write_canonical_atomic(restored_skill, workspace_key)
        return True, f"Successfully rolled back '{name}' to version {restored_skill.version}.", restored_skill

    def write_journal_atomic(self, tx_data: dict[str, Any]) -> Path:
        """Atomically write or update a transaction journal file in .history/tx_<uuid>.json."""
        tx_id = tx_data.get("tx_id", uuid.uuid4().hex)
        tx_data["tx_id"] = tx_id
        target = self._skills_dir / ".history" / f"tx_{tx_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)

        tmp = target.with_suffix(f".tmp.{os.getpid()}_{uuid.uuid4().hex[:8]}")
        try:
            content = json.dumps(tx_data, ensure_ascii=False, indent=2)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            _fsync_replace(tmp, target)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
        return target

    def update_journal_phase(self, tx_id: str, phase: str) -> None:
        """Atomically update journal phase without in-place modification."""
        target = self._skills_dir / ".history" / f"tx_{tx_id}.json"
        if not target.exists():
            return
        data = json.loads(target.read_text(encoding="utf-8"))
        data["phase"] = phase
        self.write_journal_atomic(data)

    def compensate_journal(self, tx_data: dict[str, Any]) -> bool:
        """Execute compensation for an interrupted transaction."""
        action = tx_data.get("action", "CREATE")
        name = tx_data.get("name", "")
        scope = tx_data.get("scope_key", "global")
        canonical_path = self.get_canonical_path(name, "project" if scope != "global" else "global", scope)

        # Canonical compensation
        if action == "CREATE":
            if canonical_path.exists():
                # Verify hash before deletion
                intended_hash = tx_data.get("intended_canonical_hash", "")
                if not intended_hash or _compute_file_hash(canonical_path) == intended_hash:
                    canonical_path.unlink(missing_ok=True)
        elif action in ("UPDATE", "ROLLBACK"):
            prior_snapshot = tx_data.get("prior_canonical_snapshot_path")
            if prior_snapshot and Path(prior_snapshot).exists():
                shutil.copy2(prior_snapshot, canonical_path)

        # State compensation
        prior_state_path = tx_data.get("prior_state_snapshot_path")
        if prior_state_path and Path(prior_state_path).exists():
            state_file = self._skills_dir.parent / "skill_state.json"
            shutil.copy2(prior_state_path, state_file)

        tx_data["phase"] = "COMPENSATED"
        self.write_journal_atomic(tx_data)
        return True

    def recover_pending_journals(self) -> list[str]:
        """Scan and recover/compensate pending transaction journals at startup."""
        hdir = self._skills_dir / ".history"
        if not hdir.exists():
            return []

        recovered = []
        for j_path in sorted(hdir.glob("tx_*.json")):
            try:
                data = json.loads(j_path.read_text(encoding="utf-8"))
            except Exception:
                # Corrupt journal: fail closed, move to corrupt backup
                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                corrupt_target = hdir / f"journal_corrupt_{ts}.json"
                try:
                    raw_bytes = j_path.read_bytes()
                    corrupt_target.write_bytes(raw_bytes)
                    j_path.unlink(missing_ok=True)
                except Exception:
                    pass
                recovered.append(f"Corrupt journal quarantined: {j_path.name}")
                continue

            phase = data.get("phase", "")
            if phase == "STATE_WRITTEN":
                # Both writes succeeded
                data["phase"] = "COMMITTED"
                j_path.unlink(missing_ok=True)
                recovered.append(f"Committed completed transaction: {data.get('tx_id')}")
            elif phase in ("STARTED", "CANONICAL_WRITTEN"):
                # Interrupted second write: compensate
                self.compensate_journal(data)
                j_path.unlink(missing_ok=True)
                recovered.append(f"Compensated interrupted transaction: {data.get('tx_id')}")
            elif phase in ("COMMITTED", "COMPENSATED"):
                j_path.unlink(missing_ok=True)

        return recovered
