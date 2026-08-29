"""Prompt Budget Measurement and Redacted Telemetry for Phase 4.

Records block character lengths, token estimates, and system-prompt SHA256 hashes
without leaking raw prompts, secrets, or private user memory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Optional

from ..doctor import EnvironmentProfile


@dataclass(frozen=True)
class PromptBudgetReport:
    """Redacted metrics recording prompt size and cache stability."""

    scenario: str
    voice_contract_chars: int
    environment_chars: int
    policy_chars: int
    capability_chars: int
    memory_chars: int
    total_system_prompt_chars: int
    dynamic_turn_chars: int
    estimated_total_tokens: int
    system_prompt_hash: str  # sha256 of session-stable prompt
    tools_requested_count: int = 0
    direct_descriptor_used: bool = False
    typed_state_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "voice_contract_chars": self.voice_contract_chars,
            "environment_chars": self.environment_chars,
            "policy_chars": self.policy_chars,
            "capability_chars": self.capability_chars,
            "memory_chars": self.memory_chars,
            "total_system_prompt_chars": self.total_system_prompt_chars,
            "dynamic_turn_chars": self.dynamic_turn_chars,
            "estimated_total_tokens": self.estimated_total_tokens,
            "system_prompt_hash": self.system_prompt_hash,
            "tools_requested_count": self.tools_requested_count,
            "direct_descriptor_used": self.direct_descriptor_used,
            "typed_state_used": self.typed_state_used,
        }


def estimate_tokens(text: str) -> int:
    """Deterministic token estimation (~3.5 chars per token for EN/SV mix)."""
    return max(1, len(text) // 4) if text else 0


def compute_prompt_hash(text: str) -> str:
    """Compute sha256 hash of prompt text."""
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"
