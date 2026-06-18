"""Prompt-builder — monterar systemprompt.

DIFFERENTIATORN: miljöprofilen (doctor) injiceras HÄR som beteenderegler, så
Hundens beteende ändras av hårdvaran. Inte dekoration — funktionellt.

Exempel på regler som aktiveras av profilen:
  - has_git=False  -> "blockera repo-operationer, fråga användaren"
  - has_python=False -> "föreslå PowerShell-alternativ"
  - svag CPU        -> "håll svar kompakta, undvik tunga bakgrundsjobb"
"""
from __future__ import annotations

from ..doctor import EnvironmentProfile


def capability_rules(profile: EnvironmentProfile) -> list[str]:
    rules: list[str] = []
    if not profile.has_git:
        rules.append("git saknas i miljön -> blockera repo-operationer, fråga användaren först")
    if not profile.has_python:
        rules.append("python saknas -> föreslå PowerShell-alternativ istället för python-script")
    if (profile.cpu_count or 99) <= 4:
        rules.append("begränsad CPU -> håll svar kompakta, undvik tunga bakgrundsjobb")
    if profile.has_node:
        rules.append("node finns -> kan föreslå npm/node-baserade lösningar")
    return rules


def build_system_prompt(
    persona: str,
    profile: EnvironmentProfile,
    project_context: str = "",
) -> str:
    parts: list[str] = [persona, "", "## Din miljö (du lever här)"]
    parts.append(f"- OS: {profile.os} {profile.os_version}")
    parts.append(f"- CPU: {profile.processor or 'okänd'} ({profile.cpu_count} kärnor)")
    parts.append(f"- Shell: {profile.shell}")
    parts.append(
        "- Verktyg: "
        + ", ".join(
            f"{k}={'ja' if v else 'nej'}" for k, v in profile.capabilities.items()
        )
    )

    rules = capability_rules(profile)
    if rules:
        parts.append("")
        parts.append("## Beteenderegler baserade på din miljö")
        parts.extend(f"- {r}" for r in rules)

    if project_context:
        parts.append("")
        parts.append("## Projektkontext")
        parts.append(project_context)

    return "\n".join(parts)
