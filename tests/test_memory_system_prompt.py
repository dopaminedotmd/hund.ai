"""RED/GREEN tests for system prompt memory seeding, user profile, and prompt contract (R1)."""
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from hund.agent.loop import assemble_system_prompt
from hund.agent.prompt_builder import build_system_prompt
from hund.doctor import EnvironmentProfile


def test_build_system_prompt_includes_user_profile_and_memory():
    """System prompt includes a distinct user profile section with memory bullets."""
    profile = EnvironmentProfile(os="Windows", os_version="11", shell="pwsh")
    persona = "hund är en assistent."
    memory_lines = ["User prefers strikt typning", "Namn: William"]

    prompt = build_system_prompt(
        persona=persona,
        profile=profile,
        memory_lines=memory_lines,
    )

    assert "## Användarprofil" in prompt or "## Persistent minne" in prompt
    assert "User prefers strikt typning" in prompt
    assert "Namn: William" in prompt


def test_build_system_prompt_includes_memory_contract():
    """System prompt includes the narrow memory contract prohibiting archaeology scripts."""
    profile = EnvironmentProfile(os="Windows", os_version="11", shell="pwsh")
    persona = "hund är en assistent."

    prompt = build_system_prompt(
        persona=persona,
        profile=profile,
        memory_lines=[],
    )

    assert "Minnes- och identitetskontrakt" in prompt
    # Missing facts must produce direct third-person answer without tools
    assert "utan verktyg" in prompt or "utan verktygsanrop" in prompt
    # No scripts or archaeology
    assert "skript" in prompt or "databas" in prompt


def test_assemble_system_prompt_preserves_canonical_persona_immutability():
    """Canonical persona is not mutated or injected with generic customer names."""
    profile = EnvironmentProfile(os="Windows", os_version="11", shell="pwsh")
    persona = "hund är en assistent på maskinen."

    prompt = assemble_system_prompt(
        persona,
        profile,
        memory_lines=["User prefers FastAPI"],
    )

    # Persona remains at start
    assert prompt.startswith("hund är en assistent")
    # Memory and contract are separate sections
    assert "User prefers FastAPI" in prompt


def test_build_system_prompt_injects_username_alongside_preferences():
    """When memory contains preferences without name, user's OS name is still injected in Användarprofil."""
    profile = EnvironmentProfile(os="Windows", os_version="11", shell="pwsh")
    persona = "hund är en assistent."
    memory_lines = ["User's favorite framework is FastAPI", "User prefers strikt typning"]

    with patch("getpass.getuser", return_value="William"):
        prompt = build_system_prompt(
            persona=persona,
            profile=profile,
            memory_lines=memory_lines,
        )

    assert "## Persistent minne" in prompt
    assert "User's favorite framework is FastAPI" in prompt
    assert "User prefers strikt typning" in prompt
    assert "## Användarprofil" in prompt
    assert "Namn: William" in prompt

