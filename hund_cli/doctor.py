"""hund doctor — hårdvara-/miljöprofil.

DETTA ÄR DIFFERENTIATORN. Profilen får inte bara visas — den ska injiceras i
systemprompten och ÄNDRA Hundens beteende (se docs/mvp.md komponent 2):
  - saknas git    -> blockera repo-operationer, fråga
  - svag maskin   -> varna för tunga bakgrundsjobb
  - saknas python -> föreslå PowerShell-alternativ
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class EnvironmentProfile:
    # OS
    os: str = ""
    os_version: str = ""
    os_caption: str = ""       # "Microsoft Windows 11 Pro"
    os_arch: str = ""          # "64-bit"

    # Maskin
    machine: str = ""
    processor: str = ""
    cpu_count: int | None = None
    hostname: str = ""

    # GPU
    gpu_model: str = ""        # "NVIDIA GeForce RTX 4070"
    gpu_vram_mb: int = 0       # 12282

    # RAM
    total_ram_gb: float = 0.0  # 31.8

    # Python
    python_impl: str = ""
    shell: str = ""

    # Verktyg
    has_git: bool = False
    has_python: bool = False
    has_uv: bool = False
    has_node: bool = False
    has_powershell: bool = False

    # Sökvägar
    hund_home: str = ""
    workspace: str = ""
    capabilities: dict[str, bool] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"[bold]Hund Environment Profile[/bold]",
            f"  os          : {self.os_caption or f'{self.os} {self.os_version}'} ({self.os_arch})",
            f"  hostname    : {self.hostname or 'unknown'}",
            f"  cpu         : {self.processor or 'unknown'} ({self.cpu_count} cores)",
            f"  gpu         : {self.gpu_model or 'unknown'}"
            + (f" ({self.gpu_vram_mb}MB)" if self.gpu_vram_mb else ""),
            f"  ram         : {self.total_ram_gb:.1f}GB" if self.total_ram_gb else "  ram         : unknown",
            f"  shell       : {self.shell}",
            f"  git         : {'yes' if self.has_git else '[red]no[/red]'}",
            f"  python      : {'yes' if self.has_python else '[red]no[/red]'}",
            f"  uv          : {'yes' if self.has_uv else 'no'}",
            f"  workspace   : {self.workspace}",
        ]
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def gpu_vram_gb(self) -> float:
        return self.gpu_vram_mb / 1024 if self.gpu_vram_mb else 0.0


def _which(name: str) -> bool:
    return shutil.which(name) is not None


def _wmic(query: str, *, get: str) -> str:
    """Kör wmic och returnera rå output. '' vid fel."""
    try:
        cmd = ["wmic"] + query.split() + ["get", get]
        out = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return ""
        return out.stdout.strip()
    except Exception:
        return ""


def _wmic_value(query: str, *, get: str) -> str:
    """Hämta första dataraden från wmic (skippar header)."""
    raw = _wmic(query, get=get)
    if not raw:
        return ""
    lines = raw.strip().splitlines()
    # Ta första icke-tomma raden som INTE är header-raden
    for line in lines:
        stripped = line.strip()
        if stripped and stripped != get:
            return stripped
    return ""


def _detect_os_caption() -> str:
    caption = _wmic_value("os", get="Caption")
    return caption


def _detect_os_arch() -> str:
    arch = _wmic_value("os", get="OSArchitecture")
    return arch


def _detect_gpu() -> tuple[str, int]:
    """Returnera (modellnamn, VRAM i MB)."""
    raw = _wmic("path win32_VideoController", get="AdapterRAM,name")
    if not raw:
        return "", 0
    lines = raw.strip().splitlines()
    best_vram = 0
    best_name = ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("AdapterRAM"):
            continue
        # wmic output: "AdapterRAM  Name" — VRAM först, sen namn
        # Ex: "4293918720  NVIDIA GeForce GTX 980 Ti"
        parts = stripped.split(None, 1)  # split på whitespace, max 1 split
        if len(parts) == 2 and parts[0].isdigit():
            vram = int(parts[0])
            name = parts[1].strip()
        else:
            # Fallback — hela raden som namn, ingen VRAM
            name = stripped
            vram = 0
        if vram > best_vram:
            best_vram = vram
            best_name = name
    # Konvertera bytes → MB
    if best_vram > 1024 * 1024:  # > 1GB i bytes = absolut i bytes
        best_vram = best_vram // (1024 * 1024)
    return best_name, best_vram


def _detect_ram_gb() -> float:
    """Total RAM i GB."""
    raw = _wmic_value("computersystem", get="TotalPhysicalMemory")
    if not raw:
        return 0.0
    try:
        bytes_val = int(raw)
        return bytes_val / (1024 ** 3)
    except (ValueError, TypeError):
        return 0.0


def _detect_hostname() -> str:
    """Maskinens hostname."""
    try:
        return platform.node()
    except Exception:
        return ""


def profile_environment(workspace: Path | None = None) -> EnvironmentProfile:
    """Detektera verklig miljö — inklusive GPU, RAM, hostname, OS-detaljer."""
    from .paths import hund_home

    gpu_model, gpu_vram = _detect_gpu()

    prof = EnvironmentProfile(
        os=platform.system(),
        os_version=platform.version(),
        os_caption=_detect_os_caption(),
        os_arch=_detect_os_arch(),
        machine=platform.machine(),
        processor=platform.processor() or platform.machine(),
        cpu_count=os.cpu_count(),
        hostname=_detect_hostname(),
        gpu_model=gpu_model,
        gpu_vram_mb=gpu_vram,
        total_ram_gb=_detect_ram_gb(),
        python_impl=platform.python_implementation(),
        shell=os.environ.get("SHELL", "")
        or ("powershell" if os.name == "nt" else "bash"),
        has_git=_which("git"),
        has_python=_which("python") or _which("python3"),
        has_uv=_which("uv"),
        has_node=_which("node"),
        has_powershell=_which("powershell") or _which("pwsh"),
        hund_home=str(hund_home()),
        workspace=str(workspace or Path.cwd()),
    )
    prof.capabilities = {
        "can_run_python": prof.has_python,
        "has_git": prof.has_git,
        "can_run_uv": prof.has_uv,
        "can_run_node": prof.has_node,
    }
    return prof
