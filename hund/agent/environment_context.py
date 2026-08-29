"""Canonical environment snapshot serializer with stable schema keys and localization."""
from __future__ import annotations

from typing import Literal

from ..stats.environment_snapshot import EnvironmentSnapshot, create_environment_snapshot


def get_canonical_snapshot(*, force_fresh: bool = False) -> EnvironmentSnapshot:
    """Retrieve the single authoritative environment snapshot."""
    return create_environment_snapshot(force_fresh=force_fresh)


def serialize_environment_facts(
    snapshot: EnvironmentSnapshot,
    *,
    language: str = "sv",
    include_storage_breakdown: bool = True,
) -> str:
    """Serialize structured environment facts with stable keys and localized notes.

    Stable Schema Keys:
    - CPU: Processor model and physical/logical cores
    - GPU: Graphics model name
    - GPU_VRAM: Dedicated VRAM in MiB/GiB or shared/integrated
    - SYSTEM_RAM: Total physical RAM in GiB
    - STORAGE: Mounted volume mount points, total and free capacity in GiB
    - OS: Operating system caption and architecture
    - RUNTIMES: Installed developer tooling and shell
    - OBSERVED_AT: Formatted observation timestamp (HH:MM)
    """
    is_sv = language.lower().startswith("sv")

    # Header and advisory notice
    header = (
        "[KÄND MILJÖDATA (AUKTORITATIVT SNAPSHOT) — FAKTA ÄR REDAN KÄNDA]"
        if is_sv
        else "[KNOWN ENVIRONMENT FACTS (AUTHORITATIVE SNAPSHOT) — ALREADY OBSERVED]"
    )

    lines: list[str] = [header]

    # CPU
    cpu_str = f"{snapshot.processor} ({snapshot.cpu_count} cores)"
    lines.append(f"• CPU: {cpu_str}")

    # GPU & VRAM
    gpu_model = snapshot.gpu_model or ("Integrerad" if is_sv else "Integrated")
    lines.append(f"• GPU: {gpu_model}")
    if snapshot.gpu_vram_mb:
        lines.append(f"• GPU_VRAM: {snapshot.gpu_vram_mb} MiB dedicated")
    else:
        lines.append(f"• GPU_VRAM: {'Integrerad / delat minne' if is_sv else 'Integrated / shared memory'}")

    # SYSTEM RAM
    lines.append(f"• SYSTEM_RAM: {snapshot.total_ram_gb:.1f} GiB {'totalt fysiskt minne' if is_sv else 'total physical RAM'}")

    # STORAGE
    if include_storage_breakdown and snapshot.volumes:
        storage_parts: list[str] = []
        for vol in snapshot.volumes:
            storage_parts.append(
                f"{vol.mount_point} ({vol.total_gb:.1f} GiB total, {vol.free_gb:.1f} GiB free)"
            )
        lines.append(f"• STORAGE: {'; '.join(storage_parts)}")
    elif snapshot.primary_volume:
        vol = snapshot.primary_volume
        lines.append(f"• STORAGE: {vol.mount_point} ({vol.total_gb:.1f} GiB total, {vol.free_gb:.1f} GiB free)")

    # OS
    os_info = snapshot.os_caption or f"{snapshot.os} {snapshot.os_version}"
    arch_str = f" ({snapshot.os_arch})" if snapshot.os_arch else ""
    lines.append(f"• OS: {os_info}{arch_str}")

    # RUNTIMES
    tool_names = [
        name for name, ok in [
            ("PowerShell", snapshot.has_powershell),
            ("Python", snapshot.has_python),
            ("uv", snapshot.has_uv),
            ("Git", snapshot.has_git),
            ("Node", snapshot.has_node),
        ] if ok
    ]
    runtimes_str = ", ".join(tool_names) if tool_names else "None detected"
    lines.append(f"• RUNTIMES: {runtimes_str} · Shell={snapshot.shell}")

    # OBSERVED_AT
    lines.append(f"• OBSERVED_AT: {snapshot.observation_time_display}")

    # Invariant Note
    invariant_note = (
        "* Invariant: RAM (systemminne), VRAM (grafikminne) och Disk (lagring) är helt separata resurser."
        if is_sv
        else "* Invariant: RAM (system memory), VRAM (graphics memory), and Disk (storage capacity) are strictly separate resources."
    )
    lines.append(invariant_note)

    return "\n".join(lines)
