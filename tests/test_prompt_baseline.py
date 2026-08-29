"""Baseline measurement for Phase 4 (§3.1 scenarios)."""
from hund.agent.prompt_builder import build_system_prompt
from hund.agent.prompt_budget import PromptBudgetReport, compute_prompt_hash, estimate_tokens
from hund.doctor import EnvironmentProfile
from hund.persona import load_persona


def _get_dummy_profile() -> EnvironmentProfile:
    return EnvironmentProfile(
        os="Windows",
        os_version="11 Pro",
        os_arch="x86_64",
        os_caption="Windows 11 Pro (25H2)",
        hostname="Blade-Stealth",
        cpu_count=8,
        processor="Intel(R) Core(TM) i7-8550U",
        gpu_model="NVIDIA GeForce GTX 1080 Ti",
        gpu_vram_mb=11264,
        total_ram_gb=16.0,
        shell="pwsh",
        has_git=True,
        has_python=True,
        has_node=True,
        capabilities={"git": True, "python": True, "node": True, "docker": False, "ripgrep": True},
    )


def test_baseline_measurements():
    profile = _get_dummy_profile()
    persona_raw = load_persona()

    # Scenario 1: New empty chat
    p1 = build_system_prompt(persona_raw, profile)
    r1 = PromptBudgetReport(
        scenario="1_new_empty_chat",
        voice_contract_chars=len(persona_raw),
        environment_chars=len(p1) - len(persona_raw),
        policy_chars=0,
        capability_chars=0,
        memory_chars=0,
        total_system_prompt_chars=len(p1),
        dynamic_turn_chars=0,
        estimated_total_tokens=estimate_tokens(p1),
        system_prompt_hash=compute_prompt_hash(p1),
    )
    print("\nBASELINE SCENARIO 1:", r1.to_dict())

    # Scenario 2: 'hej'
    p2 = build_system_prompt(persona_raw, profile)
    r2 = PromptBudgetReport(
        scenario="2_hej",
        voice_contract_chars=len(persona_raw),
        environment_chars=len(p2) - len(persona_raw),
        policy_chars=0,
        capability_chars=0,
        memory_chars=0,
        total_system_prompt_chars=len(p2),
        dynamic_turn_chars=len("hej"),
        estimated_total_tokens=estimate_tokens(p2 + "hej"),
        system_prompt_hash=compute_prompt_hash(p2),
    )
    print("BASELINE SCENARIO 2:", r2.to_dict())

    assert len(p1) > 0
