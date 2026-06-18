"""hund doctor — hårdvara-/miljöprofil.

DETTA ÄR DIFFERENTIATORN. Profilen får inte bara visas — den ska injiceras i
systemprompten och ÄNDRA Hundens beteende (se docs/mvp.md komponent 2):
  - saknas git    -> blockera repo-operationer, fråga
  - svag maskin   -> varna för tunga bakgrundsjobb
  - saknas python -> föreslå PowerShell-alternativ
Den injektionen byggs i fas 1 (prompt_builder).
"""
from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class EnvironmentProfile:
    os: str = ""
    os_version: str = ""
    machine: str = ""
    processor: str = ""
    cpu_count: int | None = None
    python_impl: str = ""
    shell: str = ""
    has_git: bool = False
    has_python: bool = False
    has_uv: bool = False
    has_node: bool = False
    has_powershell: bool = False
    hund_home: str = ""
    workspace: str = ""
    capabilities: dict[str, bool] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"[bold]Hund Environment Profile[/bold]",
            f"  os          : {self.os} {self.os_version}",
            f"  cpu         : {self.processor or 'unknown'} ({self.cpu_count} cores)",
            f"  shell       : {self.shell}",
            f"  git         : {'yes' if self.has_git else '[red]no[/red]'}",
            f"  python      : {'yes' if self.has_python else '[red]no[/red]'}",
            f"  uv          : {'yes' if self.has_uv else 'no'}",
            f"  workspace   : {self.workspace}",
        ]
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return asdict(self)


def _which(name: str) -> bool:
    return shutil.which(name) is not None


def profile_environment(workspace: Path | None = None) -> EnvironmentProfile:
    """Detektera verklig miljö. Stdlib-only — inga extra deps i v1."""
    from .paths import hund_home

    prof = EnvironmentProfile(
        os=platform.system(),
        os_version=platform.version(),
        machine=platform.machine(),
        processor=platform.processor() or platform.machine(),
        cpu_count=os.cpu_count(),
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
