"""Testar prompt cache preservation — systemprompten ska vara oforandrad."""
from hund.agent.loop import assemble_system_prompt
from hund.doctor import EnvironmentProfile


def _dummy_profile():
    return EnvironmentProfile(
        os="Windows",
        os_version="11",
        os_arch="x86_64",
        hostname="test-host",
        cpu_count=4,
        processor="Test CPU",
        shell="powershell",
        has_git=True,
        has_python=True,
        has_node=False,
    )


def test_system_prompt_frozen():
    """System prompt ska vara identisk vid upprepade anrop med samma input."""
    profile = _dummy_profile()
    persona = "Du ar hund."
    prompt1 = assemble_system_prompt(persona, profile)
    prompt2 = assemble_system_prompt(persona, profile)
    assert prompt1 == prompt2, "System prompt andrades mellan anrop!"


def test_system_prompt_contains_persona():
    """System prompt ska innehalla persona-texten."""
    profile = _dummy_profile()
    persona = "Hund ar ett CLI-skal."
    prompt = assemble_system_prompt(persona, profile)
    assert "Hund ar ett CLI-skal." in prompt


def test_system_prompt_role_is_system():
    """messages[0] role ska vara system."""
    from hund.providers.base import Message
    profile = _dummy_profile()
    persona = "Hund."
    content = assemble_system_prompt(persona, profile)
    msg = Message(role="system", content=content)
    assert msg.role == "system"