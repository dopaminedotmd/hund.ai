"""Comprehensive Phase 4 Before/After Prompt Measurement Matrix across 9 scenarios (§3.1)."""
from hund.agent.capability_self_model import find_matching_capabilities
from hund.agent.loop import assemble_system_prompt
from hund.agent.prompt_budget import PromptBudgetReport, compute_prompt_hash, estimate_tokens
from hund.agent.prompt_builder import build_system_prompt
from hund.agent.task_brief import TaskBrief, TaskType
from hund.agent.task_policy import classify_task
from hund.agent.turn_context import TurnContext, compose_turn_context_message, resolve_typed_state
from hund.doctor import EnvironmentProfile
from hund.persona import get_compact_voice_contract, load_canonical_persona, load_persona


def _profile() -> EnvironmentProfile:
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


def test_measure_all_nine_scenarios():
    profile = _profile()
    canonical_persona = load_canonical_persona()
    compact_persona = get_compact_voice_contract()

    scenarios = [
        ("1_new_empty_chat", ""),
        ("2_hej", "hej"),
        ("3_stable_self_knowledge", "Hur ser jag mina skills?"),
        ("4_typed_current_state", "Vilka skills är aktiva just nu?"),
        ("5_ordinary_no_tools", "Förklara vad en hash är"),
        ("6_one_tool_task", "Läs filen README.md"),
        ("7_skill_authoring_shaping", "skapa en skill för fastapi error handling"),
        ("8_long_session_compressed", "fortsätt med förra uppgiften"),
        ("9_repeated_session_stable_prompt", "hjälp mig med nästa steg"),
    ]

    results: list[dict] = []

    for name, user_text in scenarios:
        # Optimized prompt assembly
        brief = classify_task(user_text) if user_text else TaskBrief(TaskType.DIRECT_ANSWER, "empty", 1.0, "general")
        sys_prompt = assemble_system_prompt(compact_persona, profile)
        p_hash = compute_prompt_hash(sys_prompt)

        caps = find_matching_capabilities(user_text, max_results=2) if user_text else ()
        typed_state = resolve_typed_state("skills") if brief.task_type == TaskType.CURRENT_STATE else None

        turn_ctx = TurnContext(
            task_brief=brief,
            capability_descriptors=caps,
            active_state_summary=typed_state,
        )
        turn_msg = compose_turn_context_message(turn_ctx)

        report = PromptBudgetReport(
            scenario=name,
            voice_contract_chars=len(compact_persona),
            environment_chars=len(sys_prompt) - len(compact_persona),
            policy_chars=0,
            capability_chars=len(turn_msg),
            memory_chars=0,
            total_system_prompt_chars=len(sys_prompt),
            dynamic_turn_chars=len(turn_msg) + len(user_text),
            estimated_total_tokens=estimate_tokens(sys_prompt + turn_msg + user_text),
            system_prompt_hash=p_hash,
            direct_descriptor_used=len(caps) > 0,
            typed_state_used=typed_state is not None,
        )
        results.append(report.to_dict())

    print("\n--- MEASURED SCENARIO RESULTS (PHASE 4 OPTIMIZED) ---")
    for r in results:
        print(r)

    # Hash invariant: session-stable prompt hash is identical for ALL scenarios
    all_hashes = [r["system_prompt_hash"] for r in results]
    assert len(set(all_hashes)) == 1, "System prompt hash must remain 100% stable across turns in a session!"

    # Voice contract budget invariant: <= 1,500 chars
    assert results[0]["voice_contract_chars"] <= 1500
