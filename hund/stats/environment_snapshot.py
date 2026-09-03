"""Canonical EnvironmentSnapshot representing frozen host machine facts and storage metrics."""
from __future__ import annotations

import json
import os
import platform
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..doctor import EnvironmentProfile, profile_environment


@dataclass(frozen=True)
class VolumeStorage:
    """Storage metrics for a mounted disk volume."""

    mount_point: str  # e.g. "C:\\" or "/"
    total_gb: float
    free_gb: float
    used_gb: float
    safe_headroom_gb: float  # safe allocation for local models (50% of free space)


@dataclass(frozen=True)
class EnvironmentSnapshot:
    """Immutable snapshot of the host environment captured at startup or on refresh."""

    # OS & System
    os: str
    os_version: str
    os_caption: str
    os_arch: str
    hostname: str

    # CPU & GPU
    processor: str
    cpu_count: int
    gpu_model: str
    gpu_vram_mb: int

    # RAM
    total_ram_gb: float
    used_ram_gb: float

    # Storage
    primary_volume: VolumeStorage
    volumes: tuple[VolumeStorage, ...] = field(default_factory=tuple)

    # Runtimes & Tools
    has_git: bool = False
    has_python: bool = False
    has_uv: bool = False
    has_node: bool = False
    has_powershell: bool = False
    shell: str = ""
    python_impl: str = ""

    # Metadata
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def gpu_vram_gb(self) -> float:
        return self.gpu_vram_mb / 1024 if self.gpu_vram_mb else 0.0

    @property
    def observation_time_display(self) -> str:
        """Return HH:MM time string for header display."""
        try:
            dt = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
            return dt.strftime("%H:%M")
        except Exception:
            return "recent"

    def changes_since(self, previous: EnvironmentSnapshot | None) -> list[str]:
        """Detect static hardware, volume, or runtime changes (ignoring normal dynamic drift)."""
        if previous is None:
            return ["Initial environment snapshot captured."]
        changes: list[str] = []
        if self.processor != previous.processor:
            changes.append(f"CPU changed: {previous.processor} -> {self.processor}")
        if self.gpu_model != previous.gpu_model:
            changes.append(f"GPU changed: {previous.gpu_model} -> {self.gpu_model}")
        if abs(self.total_ram_gb - previous.total_ram_gb) >= 0.5:
            changes.append(f"Total RAM changed: {previous.total_ram_gb:.1f}GB -> {self.total_ram_gb:.1f}GB")
        if self.os_caption != previous.os_caption:
            changes.append(f"OS changed: {previous.os_caption} -> {self.os_caption}")
        # Runtimes
        for tool, (curr, prev) in {
            "Git": (self.has_git, previous.has_git),
            "uv": (self.has_uv, previous.has_uv),
            "Node.js": (self.has_node, previous.has_node),
            "Python": (self.has_python, previous.has_python),
        }.items():
            if curr and not prev:
                changes.append(f"Runtime installed: {tool}")
            elif prev and not curr:
                changes.append(f"Runtime removed: {tool}")
        return changes or ["No meaningful hardware or runtime changes detected."]

    def to_profile_compat(self, workspace: str = "") -> EnvironmentProfile:
        """Provide backward compatibility with legacy EnvironmentProfile consumers."""
        return EnvironmentProfile(
            os=self.os,
            os_version=self.os_version,
            os_caption=self.os_caption,
            os_arch=self.os_arch,
            machine=platform.machine(),
            processor=self.processor,
            cpu_count=self.cpu_count,
            hostname=self.hostname,
            gpu_model=self.gpu_model,
            gpu_vram_mb=self.gpu_vram_mb,
            total_ram_gb=self.total_ram_gb,
            python_impl=self.python_impl,
            shell=self.shell,
            has_git=self.has_git,
            has_python=self.has_python,
            has_uv=self.has_uv,
            has_node=self.has_node,
            has_powershell=self.has_powershell,
            workspace=workspace,
            capabilities={
                "has_git": self.has_git,
                "can_run_python": self.has_python,
                "can_run_uv": self.has_uv,
                "can_run_node": self.has_node,
            },
        )


def _get_disk_storage(path_str: str = "C:\\") -> VolumeStorage:
    """Measure disk capacity and free space on the target volume."""
    target = path_str if os.path.exists(path_str) else "."
    try:
        usage = shutil.disk_usage(target)
        total_gb = usage.total / (1024**3)
        free_gb = usage.free / (1024**3)
        used_gb = usage.used / (1024**3)
        # Safe headroom: 50% of free disk space, leaving at least 10GB margin
        safe_headroom = max(0.0, min(free_gb * 0.5, free_gb - 10.0))
        return VolumeStorage(
            mount_point=path_str if os.path.exists(path_str) else os.path.abspath(target)[:3],
            total_gb=round(total_gb, 1),
            free_gb=round(free_gb, 1),
            used_gb=round(used_gb, 1),
            safe_headroom_gb=round(safe_headroom, 1),
        )
    except Exception:
        return VolumeStorage(
            mount_point=path_str,
            total_gb=0.0,
            free_gb=0.0,
            used_gb=0.0,
            safe_headroom_gb=0.0,
        )


_CACHED_SNAPSHOT: EnvironmentSnapshot | None = None


def _snapshot_file_path(workspace: Path | str | None) -> Path:
    ws_path = Path(workspace) if workspace else Path.cwd()
    target_dir = ws_path / ".hund"
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / "environment_snapshot.json"


def _save_snapshot_to_disk(snapshot: EnvironmentSnapshot, workspace: Path | str | None) -> None:
    try:
        path = _snapshot_file_path(workspace)
        data = asdict(snapshot)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _load_snapshot_from_disk(workspace: Path | str | None) -> EnvironmentSnapshot | None:
    try:
        path = _snapshot_file_path(workspace)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        pv_data = data.pop("primary_volume", None)
        pv = VolumeStorage(**pv_data) if pv_data else _get_disk_storage()
        vols_data = data.pop("volumes", [])
        vols = tuple(VolumeStorage(**v) for v in vols_data) if vols_data else (pv,)
        return EnvironmentSnapshot(
            primary_volume=pv,
            volumes=vols,
            **data,
        )
    except Exception:
        return None


def create_environment_snapshot(
    workspace: Path | str | None = None,
    *,
    force_fresh: bool = False,
) -> EnvironmentSnapshot:
    """Create or return the cached runtime EnvironmentSnapshot.

    Persists facts to .hund/environment_snapshot.json in workspace;
    new sessions read without rescan unless force_fresh=True.
    """
    global _CACHED_SNAPSHOT
    if _CACHED_SNAPSHOT is not None and not force_fresh:
        return _CACHED_SNAPSHOT

    if not force_fresh:
        persisted = _load_snapshot_from_disk(workspace)
        if persisted is not None:
            _CACHED_SNAPSHOT = persisted
            return persisted

    prof = profile_environment(workspace=Path(workspace) if workspace else None)
    disk = _get_disk_storage("C:\\" if os.name == "nt" else "/")

    snapshot = EnvironmentSnapshot(
        os=prof.os,
        os_version=prof.os_version,
        os_caption=prof.os_caption or f"{prof.os} {prof.os_version}",
        os_arch=prof.os_arch,
        hostname=prof.hostname,
        processor=prof.processor,
        cpu_count=prof.cpu_count or os.cpu_count() or 1,
        gpu_model=prof.gpu_model,
        gpu_vram_mb=prof.gpu_vram_mb,
        total_ram_gb=round(prof.total_ram_gb, 1),
        used_ram_gb=0.0,  # dynamic utilization
        primary_volume=disk,
        volumes=(disk,),
        has_git=prof.has_git,
        has_python=prof.has_python,
        has_uv=prof.has_uv,
        has_node=prof.has_node,
        has_powershell=prof.has_powershell,
        shell=prof.shell,
        python_impl=prof.python_impl,
    )
    _CACHED_SNAPSHOT = snapshot
    _save_snapshot_to_disk(snapshot, workspace)
    return snapshot
