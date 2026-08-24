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


def _powershell(script: str) -> str:
    """Run a PowerShell -Command snippet; return stdout ('' on error/timeout)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=8,
        )
        if out.returncode != 0:
            return ""
        return out.stdout.strip()
    except Exception:
        return ""


def _detect_os_caption() -> str:
    return _powershell("(Get-CimInstance Win32_OperatingSystem).Caption")


def _detect_os_arch() -> str:
    return _powershell("(Get-CimInstance Win32_OperatingSystem).OSArchitecture")


def _detect_gpu() -> tuple[str, int]:
    """Return (model name, VRAM in MB) via CIM (WMIC removed on Win11)."""
    raw = _powershell(
        'Get-CimInstance Win32_VideoController | ForEach-Object { "{0}|{1}" -f $_.AdapterRAM, $_.Name }'
    )
    if not raw:
        return "", 0
    best_vram = 0
    best_name = ""
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            vram_str, name = line.split("|", 1)
            try:
                vram = int(vram_str.strip() or 0)
            except ValueError:
                vram = 0
        else:
            name, vram = line, 0
        if vram > best_vram:
            best_vram = vram
            best_name = name.strip()
    # Convert bytes -> MB (values > 1GB are absolute bytes).
    if best_vram > 1024 * 1024:
        best_vram //= 1024 * 1024
    return best_name, best_vram


def _detect_ram_gb() -> float:
    """Total RAM in GB."""
    raw = _powershell("(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory")
    if not raw:
        return 0.0
    try:
        return int(raw) / (1024 ** 3)
    except (ValueError, TypeError):
        return 0.0


def _detect_cpu_name() -> str:
    """Detect real human-friendly CPU model name across OSes."""
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                if name and name.strip():
                    return name.strip()
        except Exception:
            pass
    elif platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
    elif platform.system() == "Darwin":
        try:
            out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=2)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except Exception:
            pass
    return platform.processor() or platform.machine()


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
        processor=_detect_cpu_name(),
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
