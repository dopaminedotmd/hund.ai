"""hund doctor — hardware/environment profiler and read-only diagnostic checks."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Literal


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


@dataclass(frozen=True)
class CheckResult:
    """Individual diagnostic evaluation result."""

    name: str
    status: Literal["pass", "warn", "fail"]
    detail: str
    remedy: str = ""


@dataclass(frozen=True)
class DoctorReport:
    """Comprehensive read-only diagnostic report for Hund."""

    checks: tuple[CheckResult, ...]
    fix_plan: tuple[str, ...] = ()

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "pass")

    @property
    def warnings_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "warn")

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "fail")

    @property
    def summary_text(self) -> str:
        return f"{self.passed_count} passed · {self.warnings_count} warnings · {self.failed_count} failed"


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


_SYSTEM_PROBE_SCRIPT = (
    "$os = Get-CimInstance Win32_OperatingSystem;"
    "$cs = Get-CimInstance Win32_ComputerSystem;"
    "$gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object {"
    " [pscustomobject]@{ adapterRAM = $_.AdapterRAM; name = $_.Name }"
    "});"
    "[pscustomobject]@{"
    " caption = $os.Caption;"
    " arch = $os.OSArchitecture;"
    " ram_bytes = $cs.TotalPhysicalMemory;"
    " gpus = $gpus"
    "} | ConvertTo-Json -Compress"
)


def probe_system() -> dict[str, Any]:
    """One PowerShell round trip: OS caption/arch, RAM bytes and WMI GPUs as JSON."""
    raw = _powershell(_SYSTEM_PROBE_SCRIPT)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def parse_nvidia_smi_output(raw: str) -> tuple[str, int]:
    """Parse nvidia-smi csv output (name,memory.total) returning (best_name, best_vram_mb)."""
    if not raw or not raw.strip():
        return "", 0
    best_name = ""
    best_vram = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line or "," not in line:
            continue
        name, vram_str = line.split(",", 1)
        try:
            vram = int(vram_str.strip())
        except ValueError:
            vram = 0
        if vram > best_vram:
            best_vram = vram
            best_name = name.strip()
    return best_name, best_vram


def parse_wmi_gpu_output(raw: str) -> tuple[str, int]:
    """Parse WMI AdapterRAM|Name output returning (best_name, best_vram_mb)."""
    if not raw or not raw.strip():
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


def _detect_gpu(wmi_gpus: list[dict[str, Any]] | None = None) -> tuple[str, int]:
    """Return (model name, VRAM in MB) prioritizing true discrete GPU hardware VRAM."""
    # 1. Try nvidia-smi first (exact hardware VRAM, immune to 32-bit WMI wrap-around)
    if _which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=4,
            )
            if out.returncode == 0 and out.stdout.strip():
                name, vram = parse_nvidia_smi_output(out.stdout)
                if name and vram > 0:
                    return name, vram
        except Exception:
            pass

    # 2. Fallback to WMI GPU data from the single system probe.
    if wmi_gpus:
        raw = "\n".join(
            f"{gpu.get('adapterRAM') or 0}|{gpu.get('name') or ''}"
            for gpu in wmi_gpus
            if isinstance(gpu, dict)
        )
        return parse_wmi_gpu_output(raw)
    return "", 0


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


def probe_shell() -> str:
    """Detect actual shell running via subprocess."""
    try:
        if os.name == "nt":
            proc = subprocess.run(
                "ver",
                shell=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            out = proc.stdout.strip()
            if "Microsoft Windows" in out or "Windows" in out:
                return f"cmd.exe ({out})"
            return "cmd.exe"
        else:
            proc = subprocess.run(
                "echo $0",
                shell=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            out = proc.stdout.strip()
            if out and not out.startswith("$"):
                return out
            return os.environ.get("SHELL", "bash")
    except Exception:
        return "okänd"


def profile_environment(
    workspace: Path | None = None,
    *,
    shell: str | None = None,
) -> EnvironmentProfile:
    """Detektera verklig miljö — inklusive GPU, RAM, hostname, OS-detaljer."""
    from .paths import hund_home

    sysinfo = probe_system()
    gpus = sysinfo.get("gpus") or []
    if not isinstance(gpus, list):
        gpus = []
    gpu_model, gpu_vram = _detect_gpu(wmi_gpus=gpus)

    try:
        total_ram_gb = float(sysinfo.get("ram_bytes") or 0) / (1024 ** 3)
    except (ValueError, TypeError):
        total_ram_gb = 0.0

    prof = EnvironmentProfile(
        os=platform.system(),
        os_version=platform.version(),
        os_caption=str(sysinfo.get("caption") or ""),
        os_arch=str(sysinfo.get("arch") or ""),
        machine=platform.machine(),
        processor=_detect_cpu_name(),
        cpu_count=os.cpu_count(),
        hostname=_detect_hostname(),
        gpu_model=gpu_model,
        gpu_vram_mb=gpu_vram,
        total_ram_gb=total_ram_gb,
        python_impl=platform.python_implementation(),
        shell=shell or probe_shell(),
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


def _check_context_window(cfg: Any) -> CheckResult:
    """Flag configs whose context window exceeds the model's true window (Track 21)."""
    from .providers.catalog import catalog_context_window

    provider = getattr(cfg, "provider", None)
    model = getattr(provider, "model", "") or "unknown"
    configured = int(getattr(provider, "context_window", 0) or 0)
    truthful = catalog_context_window(model)
    if truthful is None:
        return CheckResult(
            name="Context window",
            status="pass",
            detail=f"{configured:,} tokens ({model} not in catalog; unverified)",
        )
    if configured > truthful:
        return CheckResult(
            name="Context window",
            status="warn",
            detail=f"Configured {configured:,} exceeds {model} true window {truthful:,}",
            remedy="Restart Hund so the config loader corrects the value, or re-select the model in /model.",
        )
    return CheckResult(
        name="Context window",
        status="pass",
        detail=f"{configured:,} of {truthful:,} ({model})",
    )


def diagnose_system(rt: Any = None, workspace: Path | None = None) -> DoctorReport:
    """Run structured read-only health checks on Hund and integrations."""
    from .config import HundConfig
    from .secrets import get_credential_status
    from .stats.environment_snapshot import create_environment_snapshot

    checks: list[CheckResult] = []
    fix_plan: list[str] = []

    # 1. Environment snapshot check
    try:
        snapshot = create_environment_snapshot(workspace)
        if snapshot.processor and snapshot.total_ram_gb > 0:
            checks.append(CheckResult(
                name="Environment snapshot",
                status="pass",
                detail="Current",
            ))
        else:
            checks.append(CheckResult(
                name="Environment snapshot",
                status="warn",
                detail="Partial sensor data",
                remedy="Run /system refresh to re-evaluate hardware metrics.",
            ))
            fix_plan.append("Re-scan hardware metrics via /system refresh")
    except Exception as exc:
        checks.append(CheckResult(
            name="Environment snapshot",
            status="fail",
            detail="Snapshot evaluation failed",
            remedy="Check host permissions for hardware inspection.",
        ))
        fix_plan.append("Verify system discovery permissions")

    # 2. Config & Recovery check
    try:
        cfg = getattr(rt, "cfg", None) or HundConfig.load()
        if cfg and getattr(cfg, "provider", None) and cfg.provider.model:
            checks.append(CheckResult(
                name="Config and recovery",
                status="pass",
                detail="Healthy",
            ))
        else:
            checks.append(CheckResult(
                name="Config and recovery",
                status="warn",
                detail="Default configuration",
                remedy="Run /config to verify your settings.",
            ))
            fix_plan.append("Save configuration with /config")
    except Exception:
        checks.append(CheckResult(
            name="Config and recovery",
            status="fail",
            detail="Configuration error",
            remedy="Restore config from backup or reset with /config reset.",
        ))
        fix_plan.append("Restore configuration defaults")

    # 3. Provider credentials check
    try:
        cfg = getattr(rt, "cfg", None) or HundConfig.load()
        active_model = getattr(cfg.provider, "model", "deepseek-chat")
        cred_id = getattr(cfg.provider, "credential_id", "deepseek")
        env_name = getattr(cfg.provider, "api_key_env", "DEEPSEEK_API_KEY")
        status, _info = get_credential_status(cred_id, env_name)
        if status in ("configured", "environment"):
            checks.append(CheckResult(
                name="Provider credentials",
                status="pass",
                detail=f"{cred_id.title()} [{status.title()}]",
            ))
        else:
            checks.append(CheckResult(
                name="Provider credentials",
                status="warn",
                detail=f"{cred_id.title()} needs a key",
                remedy=f"Use /auth to configure API key for {cred_id}.",
            ))
            fix_plan.append(f"Configure {cred_id} API key in /auth")
    except Exception:
        checks.append(CheckResult(
            name="Provider credentials",
            status="warn",
            detail="Credential vault unverified",
            remedy="Check Windows Credential Manager accessibility.",
        ))
        fix_plan.append("Verify keyring access in /auth")

    # 4. Selected model consistency
    try:
        cfg = getattr(rt, "cfg", None) or HundConfig.load()
        active_model = getattr(cfg.provider, "model", "deepseek-chat")
        checks.append(CheckResult(
            name="Selected model",
            status="pass",
            detail=f"{active_model}",
        ))
    except Exception:
        checks.append(CheckResult(
            name="Selected model",
            status="warn",
            detail="Unknown model",
            remedy="Select an active model in /model.",
        ))
        fix_plan.append("Select active model via /model")

    # 5. Context window truthfulness (Track 21)
    try:
        cfg = getattr(rt, "cfg", None) or HundConfig.load()
        context_check = _check_context_window(cfg)
        checks.append(context_check)
        if context_check.status == "warn":
            fix_plan.append("Correct the provider context window via /model or restart")
    except Exception:
        checks.append(CheckResult(
            name="Context window",
            status="warn",
            detail="Window unverified",
            remedy="Verify the active model's context window in /model.",
        ))
        fix_plan.append("Verify context window via /model")

    # 6. Learning store check
    try:
        from .store.sqlite import connect_requests
        conn = connect_requests()
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        conn.close()
        checks.append(CheckResult(
            name="Learning store",
            status="pass",
            detail="Schema current",
        ))
    except Exception:
        checks.append(CheckResult(
            name="Learning store",
            status="warn",
            detail="Database offline",
            remedy="Run /reset if local learning database is corrupted.",
        ))
        fix_plan.append("Verify learning store schema")

    # 7. Terminal capabilities & profile
    try:
        from .ui import theme
        if theme.supports_truecolor():
            checks.append(CheckResult(
                name="Terminal profile",
                status="pass",
                detail="Truecolor enabled",
            ))
        else:
            checks.append(CheckResult(
                name="Terminal profile",
                status="warn",
                detail="Standard color mode",
                remedy="Use Windows Terminal for 24-bit Truecolor and Nerd Font rendering.",
            ))
            fix_plan.append("Enable Truecolor in terminal settings")
    except Exception:
        checks.append(CheckResult(
            name="Terminal profile",
            status="pass",
            detail="Standard",
        ))

    return DoctorReport(checks=tuple(checks), fix_plan=tuple(fix_plan))
