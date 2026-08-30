"""Versioned, atomic persistence for specialization snapshots."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import uuid
from typing import Any

from .contracts import SpecializationSnapshot, parse_contract

SCHEMA_VERSION = 1


class StorageConflict(RuntimeError):
    """Raised when a compare-and-swap write observes a newer state."""

    def __init__(self, code: str = "storage_version_conflict") -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StoredSnapshot:
    version: int
    snapshot: SpecializationSnapshot


class SpecializationStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self.quarantine_dir = self.path.parent / "quarantine"

    def load(self) -> StoredSnapshot:
        if not self.path.exists():
            if self.backup_path.exists():
                return self._read(self.backup_path)
            return StoredSnapshot(0, _empty_snapshot())
        try:
            return self._read(self.path)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._quarantine_current()
            if self.backup_path.exists():
                shutil.copy2(self.backup_path, self.path)
                return self._read(self.backup_path)
            return StoredSnapshot(0, _empty_snapshot())

    def save(self, snapshot: SpecializationSnapshot, *, expected_version: int) -> int:
        current = self.load()
        if current.version != expected_version:
            raise StorageConflict()
        next_version = current.version + 1
        payload = {
            "schema_version": SCHEMA_VERSION,
            "version": next_version,
            "snapshot": snapshot.to_dict(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(f"{self.path.name}.tmp.{uuid.uuid4().hex}")
        try:
            if self.path.exists():
                os.replace(self.path, self.backup_path)
            with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            if not self.backup_path.exists():
                shutil.copy2(self.path, self.backup_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise
        return next_version

    def _read(self, path: Path) -> StoredSnapshot:
        with path.open("r", encoding="utf-8") as handle:
            data: dict[str, Any] = json.load(handle)
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported specialization storage schema")
        return StoredSnapshot(int(data["version"]), parse_contract(data["snapshot"]))

    def _quarantine_current(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        target = self.quarantine_dir / f"corrupt-{uuid.uuid4().hex}.json"
        target.write_text(json.dumps({"reason": "corrupt_state", "raw": raw}), encoding="utf-8")


def _empty_snapshot() -> SpecializationSnapshot:
    from .contracts import Profile

    return SpecializationSnapshot(Profile("default", "Default", "global", (), 0), (), (), (), (), False)
