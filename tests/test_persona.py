"""Persona-gate (MVP komponent 7b): systemprompten bevarar Hunds identitet.

Statisk regression: kollar att persona + miljö binds in korrekt. Bevisar att
persona inte tappas när profil injiceras.
"""
from __future__ import annotations

from hund.agent.prompt_builder import build_system_prompt
from hund.doctor import EnvironmentProfile
from hund.persona import load_persona


def _profile() -> EnvironmentProfile:
    return EnvironmentProfile(
        os="Windows", cpu_count=8, has_git=True, has_python=True,
        has_node=True, shell="pwsh", capabilities={"has_git": True},
    )


def test_persona_identity_preserved():
    """Persona (riktig hund.md eller skeleton) behåller Hunds identitet."""
    prompt = build_system_prompt(load_persona(), _profile())
    assert "hund" in prompt.lower()  # identitet bevarad oavsett källa


def test_environment_bound_not_decorative():
    prompt = build_system_prompt(load_persona(), _profile())
    assert "Din miljö" in prompt  # miljö-sektion injiceras
    assert "Windows" in prompt
    assert "8" in prompt  # cpu_count
