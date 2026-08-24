"""Skill v1 — strukturerad instruktion + safety + verification.

Viktigt: en Skill är INTE exekverbar kod. Den är en deklarativ beskrivning av
när och hur Hund ska agera, med inbyggda gränser (forbidden_actions) och
verifiering. Ingen skill får höja permissions eller kringgå PermissionEngine.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# safety_level: hur mycket mänsklig bekräftelse ett steg i skillen kräver.
SAFETY_LEVELS = frozenset({"read_only", "confirm", "confirm_for_write"})
LIFECYCLE_STATES = frozenset({
    "draft", "schema_valid", "sandbox_tested", "active", "proven",
    "quarantined", "deprecated", "rolled_back",
})
VAULT_STATES = frozenset({"equipped", "parked", "vaulted"})
# Compatibility export used by the validator.
STATUSES = LIFECYCLE_STATES

MAX_ACTIVE_SKILLS = 6

# Verktyg/handlingar som en skill ALDRIG får kräva eller tillåta — dessa är TCB.
BANNED_ACTIONS = frozenset(
    {"self_update", "apply_update", "modify_tcb", "elevate_permissions"}
)

@dataclass(frozen=True)
class KnowledgeRef:
    knowledge_id: str
    version: str


@dataclass(frozen=True)
class Skill:
    schema_version: int
    name: str
    domain: str
    status: str
    triggers: tuple[str, ...]
    when_to_use: str
    steps: tuple[str, ...]
    required_tools: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    safety_level: str
    verification: tuple[str, ...]
    examples: tuple[str, ...] = ()
    immutable: bool = False
    lifecycle_state: str = ""
    vault_state: str = ""
    user_pinned: bool = False
    version: str = "1.0.0"
    capability_id: str = ""
    scope: str = "global"
    source_knowledge_refs: tuple[KnowledgeRef, ...] = ()
    created_from_event_ids: tuple[str, ...] = ()
    use_count: int = 0
    successful_use_count: int = 0
    failure_count: int = 0
    cross_session_success: int = 0
    last_used_at: Optional[str] = None
    health: float = 1.0
    revalidation_required: bool = False

    def __post_init__(self) -> None:
        lifecycle = self.lifecycle_state
        vault = self.vault_state
        legacy = self.status.strip()
        if not lifecycle:
            if legacy == "vaulted":
                lifecycle, vault = "active", vault or "vaulted"
            elif legacy == "disabled":
                lifecycle, vault = "deprecated", vault or "vaulted"
            else:
                lifecycle = legacy if legacy in LIFECYCLE_STATES else "draft"
                vault = vault or ("equipped" if legacy == "active" else "vaulted")
        if lifecycle not in {"active", "proven"} and vault == "equipped":
            vault = "vaulted"
        if vault not in VAULT_STATES:
            vault = "vaulted"
        object.__setattr__(self, "lifecycle_state", lifecycle)
        object.__setattr__(self, "vault_state", vault)
        # Deprecated field remains serialized for old readers, but means lifecycle only.
        object.__setattr__(self, "status", lifecycle)

    def summary(self) -> str:
        """Kompakt rad för prompt-injektion (ej full skill-dump)."""
        return f"[{self.name}] ({self.domain}) {self.when_to_use}"

    def to_dict(self) -> dict:
        d = {
            "schema_version": self.schema_version,
            "name": self.name,
            "domain": self.domain,
            "status": self.lifecycle_state,
            "lifecycle_state": self.lifecycle_state,
            "vault_state": self.vault_state,
            "scope": self.scope,
            "user_pinned": self.user_pinned,
            "version": self.version,
            "capability_id": self.capability_id,
            "source_knowledge_refs": [
                {"knowledge_id": ref.knowledge_id, "version": ref.version}
                for ref in self.source_knowledge_refs
            ],
            "created_from_event_ids": list(self.created_from_event_ids),
            "triggers": list(self.triggers),
            "when_to_use": self.when_to_use,
            "steps": list(self.steps),
            "required_tools": list(self.required_tools),
            "forbidden_actions": list(self.forbidden_actions),
            "safety_level": self.safety_level,
            "verification": list(self.verification),
            "examples": list(self.examples),
            "use_count": self.use_count,
            "successful_use_count": self.successful_use_count,
            "failure_count": self.failure_count,
            "cross_session_success": self.cross_session_success,
            "last_used_at": self.last_used_at,
            "health": self.health,
            "revalidation_required": self.revalidation_required,
        }
        if self.immutable:
            d["immutable"] = True
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Skill":
        raw_forbidden = set(str(a) for a in d.get("forbidden_actions", []))
        forbidden = tuple(sorted(raw_forbidden | BANNED_ACTIONS))

        parsed_steps = []
        for s in d.get("steps", []):
            if isinstance(s, dict):
                phase = s.get("phase", "")
                actions = s.get("actions", [])
                if isinstance(actions, list):
                    action_str = "; ".join(str(a) for a in actions)
                    parsed_steps.append(f"[{phase}] {action_str}" if phase else action_str)
                else:
                    parsed_steps.append(str(s))
            else:
                parsed_steps.append(str(s))

        raw_status = str(d.get("status", "draft")).strip()
        if "lifecycle_state" in d:
            lifecycle = str(d.get("lifecycle_state", "draft")).strip()
            vault = str(d.get("vault_state", "vaulted")).strip()
        elif raw_status == "vaulted":
            lifecycle, vault = "active", "vaulted"
        elif raw_status == "active":
            lifecycle, vault = "active", "equipped"
        elif raw_status == "disabled":
            lifecycle, vault = "deprecated", "vaulted"
        else:
            lifecycle = raw_status if raw_status in LIFECYCLE_STATES else "draft"
            vault = "vaulted"
        if lifecycle not in {"active", "proven"} and vault == "equipped":
            vault = "vaulted"
        raw_refs = d.get("source_knowledge_refs", [])
        refs = tuple(
            KnowledgeRef(str(ref.get("knowledge_id", "")), str(ref.get("version", "")))
            for ref in raw_refs if isinstance(ref, dict) and ref.get("knowledge_id")
        )
        raw_tools = d.get("required_tools")
        if raw_tools is None:
            raw_tools = d.get("tools", [])
        return cls(
            schema_version=int(d.get("schema_version", 0)),
            name=str(d.get("name", "")).strip(),
            domain=str(d.get("domain", "")).strip(),
            status=lifecycle,
            triggers=tuple(str(t) for t in d.get("triggers", [])),
            when_to_use=str(d.get("when_to_use", "")).strip(),
            steps=tuple(parsed_steps),
            required_tools=tuple(str(t) for t in raw_tools),
            forbidden_actions=forbidden,
            safety_level=str(d.get("safety_level", "")).strip(),
            verification=tuple(str(v) for v in d.get("verification", [])),
            examples=tuple(str(e) for e in d.get("examples", [])),
            immutable=bool(d.get("immutable", False)),
            lifecycle_state=lifecycle,
            vault_state=vault,
            user_pinned=bool(d.get("user_pinned", False)),
            version=str(d.get("version", "1.0.0")),
            capability_id=str(d.get("capability_id", "")),
            scope=str(d.get("scope", "global")),
            source_knowledge_refs=refs,
            created_from_event_ids=tuple(str(v) for v in d.get("created_from_event_ids", [])),
            use_count=int(d.get("use_count", 0)),
            successful_use_count=int(d.get("successful_use_count", 0)),
            failure_count=int(d.get("failure_count", 0)),
            cross_session_success=int(d.get("cross_session_success", 0)),
            last_used_at=d.get("last_used_at"),
            health=float(d.get("health", 1.0)),
            revalidation_required=bool(d.get("revalidation_required", False)),
        )
