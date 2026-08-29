"""Canonical contracts, value objects, and lineage/receipt foundations for Hund skills."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Optional, Sequence
import uuid

# Schema contracts
CURRENT_SCHEMA_VERSION = 1
MIN_SUPPORTED_SCHEMA_VERSION = 1
MAX_SUPPORTED_SCHEMA_VERSION = 1

# Publication statuses
PUBLICATION_STATUS_PUBLISHED = "published"
PUBLICATION_STATUS_QUARANTINED = "quarantined"
PUBLICATION_STATUS_DRAFT = "draft"
PUBLICATION_STATUS_RETIRED = "retired"

VALID_PUBLICATION_STATUSES = frozenset({
    PUBLICATION_STATUS_PUBLISHED,
    PUBLICATION_STATUS_QUARANTINED,
    PUBLICATION_STATUS_DRAFT,
    PUBLICATION_STATUS_RETIRED,
})

# Research choices
class ResearchChoice:
    NOT_NEEDED = "not_needed"
    EXPLICITLY_REQUESTED = "explicitly_requested"
    USER_APPROVED = "user_approved"
    EXISTING_CONTEXT = "existing_context"
    DECLINED_WITH_LIMITATION = "declined_with_limitation"


VALID_RESEARCH_CHOICES = frozenset({
    ResearchChoice.NOT_NEEDED,
    ResearchChoice.EXPLICITLY_REQUESTED,
    ResearchChoice.USER_APPROVED,
    ResearchChoice.EXISTING_CONTEXT,
    ResearchChoice.DECLINED_WITH_LIMITATION,
})

# Secret and private path patterns for safety sanitization in research sources
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[^\s,;]+"),
)
_PRIVATE_PATH_PATTERNS = (
    re.compile(r"\b[A-Za-z]:\\(?:Users|Documents and Settings)\\", re.I),
    re.compile(r"(?<!\S)/(?:Users|home)/[^\s\r\n]+", re.I),
)


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9_-]+", "-", (value or "").casefold()).strip("-")
    return (value or "skill")[:64]


def compute_legacy_lineage_id(capability_id: str, scope: str = "global", workspace_key: str = "global") -> str:
    """Derive deterministic, opaque lineage identity for legacy skills."""
    norm_cap = _slug(capability_id)
    norm_scope = (scope or "global").strip().casefold()
    norm_ws = (workspace_key or "global").strip().casefold()
    seed = f"hund:lineage:v1:{norm_scope}:{norm_ws}:{norm_cap}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"lin_{digest}"


def generate_lineage_id() -> str:
    """Generate a fresh unique lineage ID for newly created skills."""
    return f"lin_{uuid.uuid4().hex[:16]}"


@dataclass(frozen=True)
class ResearchSource:
    """Provenance reference for authoritative research sources."""

    title: str
    url_or_ref: str
    provenance: str = ""
    as_of: Optional[str] = None

    def __post_init__(self) -> None:
        validate_research_source(self)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "title": self.title,
            "url_or_ref": self.url_or_ref,
        }
        if self.provenance:
            d["provenance"] = self.provenance
        if self.as_of:
            d["as_of"] = self.as_of
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchSource:
        return cls(
            title=str(data.get("title", "")),
            url_or_ref=str(data.get("url_or_ref", "")),
            provenance=str(data.get("provenance", "")),
            as_of=data.get("as_of"),
        )


def validate_research_source(source: ResearchSource) -> None:
    """Verify that research sources contain no credentials or private local paths."""
    combined = f"{source.title} {source.url_or_ref} {source.provenance}"
    for pat in _SECRET_PATTERNS:
        if pat.search(combined):
            raise ValueError(f"ResearchSource contains forbidden credential pattern: {source.url_or_ref[:30]}")
    for pat in _PRIVATE_PATH_PATTERNS:
        if pat.search(combined):
            raise ValueError(f"ResearchSource contains forbidden private path: {source.url_or_ref[:30]}")


@dataclass(frozen=True)
class ResearchMetadata:
    """Typed research provenance and freshness metadata."""

    choice: str = ResearchChoice.NOT_NEEDED
    sources: tuple[ResearchSource, ...] = ()
    freshness_as_of: Optional[str] = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.choice not in VALID_RESEARCH_CHOICES:
            raise ValueError(f"Invalid research choice: {self.choice!r}. Must be one of {sorted(VALID_RESEARCH_CHOICES)}")
        if self.freshness_as_of is not None:
            # Must parse as valid ISO date / datetime
            try:
                # Support standard ISO format
                iso_str = self.freshness_as_of.replace("Z", "+00:00")
                datetime.fromisoformat(iso_str)
            except Exception as exc:
                raise ValueError(f"Invalid freshness_as_of timestamp (must be ISO-8601): {self.freshness_as_of!r}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "choice": self.choice,
            "sources": [s.to_dict() for s in self.sources],
            "freshness_as_of": self.freshness_as_of,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchMetadata:
        if not data:
            return cls()
        sources = tuple(ResearchSource.from_dict(s) for s in data.get("sources", []))
        return cls(
            choice=data.get("choice", ResearchChoice.NOT_NEEDED),
            sources=sources,
            freshness_as_of=data.get("freshness_as_of"),
            limitations=tuple(data.get("limitations", ())),
        )


@dataclass(frozen=True)
class PublicationReceipt:
    """Canonical receipt proving the published version and lineage of a skill."""

    publication_receipt_id: str = ""
    lineage_id: str = ""
    schema_version: int = 1
    artifact_version: int = 1
    capability_id: str = ""
    skill_name: str = ""
    scope: str = "global"
    publication_status: str = PUBLICATION_STATUS_PUBLISHED
    action: str = "created"  # "created" | "updated"
    lifecycle_state: str = "active"
    vault_state: str = "equipped"
    personal_skill_xp: int = 0
    source_count: int = 0
    validation_checks: tuple[str, ...] = ()
    diff_summary: Optional[str] = None
    limitations: tuple[str, ...] = ()
    published_at: str = ""
    research_metadata: Optional[ResearchMetadata] = None
    version: Optional[str] = None

    def __post_init__(self) -> None:
        if self.version is not None and self.artifact_version == 1:
            try:
                major = int(str(self.version).split(".")[0])
                object.__setattr__(self, "artifact_version", major)
            except Exception:
                pass
        elif self.version is None:
            object.__setattr__(self, "version", f"{self.artifact_version}.0.0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "publication_receipt_id": self.publication_receipt_id,
            "lineage_id": self.lineage_id,
            "schema_version": self.schema_version,
            "artifact_version": self.artifact_version,
            "capability_id": self.capability_id,
            "skill_name": self.skill_name,
            "scope": self.scope,
            "publication_status": self.publication_status,
            "action": self.action,
            "lifecycle_state": self.lifecycle_state,
            "vault_state": self.vault_state,
            "personal_skill_xp": self.personal_skill_xp,
            "source_count": self.source_count,
            "validation_checks": list(self.validation_checks),
            "diff_summary": self.diff_summary,
            "limitations": list(self.limitations),
            "published_at": self.published_at,
            "research_metadata": self.research_metadata.to_dict() if self.research_metadata else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PublicationReceipt:
        r_meta_raw = data.get("research_metadata")
        r_meta = ResearchMetadata.from_dict(r_meta_raw) if r_meta_raw else None
        return cls(
            publication_receipt_id=data.get("publication_receipt_id", ""),
            lineage_id=data.get("lineage_id", ""),
            schema_version=int(data.get("schema_version", 1)),
            artifact_version=int(data.get("artifact_version", 1)),
            capability_id=data.get("capability_id", ""),
            skill_name=data.get("skill_name", ""),
            scope=data.get("scope", "global"),
            publication_status=data.get("publication_status", PUBLICATION_STATUS_PUBLISHED),
            action=data.get("action", "created"),
            lifecycle_state=data.get("lifecycle_state", "active"),
            vault_state=data.get("vault_state", "equipped"),
            personal_skill_xp=int(data.get("personal_skill_xp", 0)),
            source_count=int(data.get("source_count", 0)),
            validation_checks=tuple(data.get("validation_checks", ())),
            diff_summary=data.get("diff_summary"),
            limitations=tuple(data.get("limitations", ())),
            published_at=data.get("published_at", ""),
            research_metadata=r_meta,
        )


def create_publication_receipt(
    skill: Any,
    action: str = "created",
    receipt_id: Optional[str] = None,
    checks_passed: int = 12,
    total_checks: int = 12,
    diff_summary: Optional[str] = None,
) -> PublicationReceipt:
    """Construct a consistent publication receipt directly from a canonical Skill."""
    rec_id = receipt_id or skill.publication_receipt_id or f"rec_{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    return PublicationReceipt(
        publication_receipt_id=rec_id,
        lineage_id=skill.lineage_id,
        schema_version=skill.schema_version,
        artifact_version=skill.artifact_version,
        capability_id=skill.capability_id,
        skill_name=skill.name,
        scope=skill.scope,
        publication_status=getattr(skill, "publication_status", PUBLICATION_STATUS_PUBLISHED),
        action=action,
        lifecycle_state=skill.lifecycle_state,
        vault_state=skill.vault_state,
        personal_skill_xp=getattr(skill, "personal_skill_xp", 0),
        source_count=len(skill.research_metadata.sources) if getattr(skill, "research_metadata", None) else 0,
        validation_checks=tuple(f"check_{i+1}:passed" for i in range(checks_passed)),
        diff_summary=diff_summary,
        limitations=getattr(skill.research_metadata, "limitations", ()) if getattr(skill, "research_metadata", None) else (),
        published_at=now_iso,
        research_metadata=getattr(skill, "research_metadata", None),
    )


def validate_receipt_against_skill(receipt: PublicationReceipt, skill: Any) -> bool:
    """Verify that a publication receipt strictly matches the skill's persisted identity and version."""
    if receipt.lineage_id != skill.lineage_id:
        return False
    if receipt.artifact_version != skill.artifact_version:
        return False
    if receipt.scope != skill.scope:
        return False
    if receipt.publication_status != getattr(skill, "publication_status", PUBLICATION_STATUS_PUBLISHED):
        return False
    if skill.publication_receipt_id and receipt.publication_receipt_id != skill.publication_receipt_id:
        return False
    return True


def apply_transition(
    skill: Any,
    transition_type: str,
    *,
    new_steps: Optional[Sequence[str]] = None,
    new_triggers: Optional[Sequence[str]] = None,
    new_when_to_use: Optional[str] = None,
    new_required_tools: Optional[Sequence[str]] = None,
    new_forbidden_actions: Optional[Sequence[str]] = None,
    new_verification: Optional[Sequence[str]] = None,
    new_name: Optional[str] = None,
    xp_gain: int = 0,
) -> Any:
    """Apply atomic state or procedure transitions according to the canonical version matrix.

    - Non-semantic (equip, park, use_evidence, read): same lineage_id, same artifact_version.
    - Semantic procedure refinement (semantic_update): same lineage_id, artifact_version + 1.
    - Fork / variant: new lineage_id, parent references set, artifact_version reset to 1.
    """
    if transition_type == "equip":
        return replace(skill, vault_state="equipped")

    if transition_type == "park":
        return replace(skill, vault_state="vaulted")

    if transition_type == "use_evidence":
        new_count = skill.use_count + 1
        new_success = skill.successful_use_count + 1
        new_xp = getattr(skill, "personal_skill_xp", 0) + xp_gain
        return replace(
            skill,
            use_count=new_count,
            successful_use_count=new_success,
            personal_skill_xp=new_xp,
        )

    if transition_type == "semantic_update":
        updates: dict[str, Any] = {
            "artifact_version": skill.artifact_version + 1,
        }
        if new_steps is not None:
            updates["steps"] = tuple(new_steps)
        if new_triggers is not None:
            updates["triggers"] = tuple(new_triggers)
        if new_when_to_use is not None:
            updates["when_to_use"] = new_when_to_use
        if new_required_tools is not None:
            updates["required_tools"] = tuple(new_required_tools)
        if new_forbidden_actions is not None:
            updates["forbidden_actions"] = tuple(new_forbidden_actions)
        if new_verification is not None:
            updates["verification"] = tuple(new_verification)
        return replace(skill, **updates)

    if transition_type == "fork":
        new_lin = generate_lineage_id()
        name = new_name or f"{skill.name}-variant"
        return replace(
            skill,
            name=name,
            capability_id=_slug(name),
            lineage_id=new_lin,
            artifact_version=1,
            parent_lineage_ref=skill.lineage_id,
            parent_version_ref=skill.artifact_version,
            publication_receipt_id=None,
        )

    raise ValueError(f"Unknown transition type: {transition_type!r}")


@dataclass(frozen=True)
class ResearchGrant:
    """Task-scoped authorization for external research in skill authoring."""

    grant_id: str
    session_id: str
    purpose: str
    choice: str = ResearchChoice.EXPLICITLY_REQUESTED
    allowed_tools: tuple[str, ...] = ("web_search", "fetch_web_page", "read_url_content", "web_open", "web_extract")
    created_at: str = ""
    expires_at: Optional[str] = None

    def is_valid(self, tool_name: str | None = None) -> bool:
        if self.choice in (
            ResearchChoice.NOT_NEEDED,
            ResearchChoice.EXISTING_CONTEXT,
            ResearchChoice.DECLINED_WITH_LIMITATION,
        ):
            return False
        if tool_name is not None and tool_name not in self.allowed_tools:
            return False
        if self.expires_at:
            try:
                exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > exp:
                    return False
            except Exception:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "session_id": self.session_id,
            "purpose": self.purpose,
            "choice": self.choice,
            "allowed_tools": list(self.allowed_tools),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchGrant:
        return cls(
            grant_id=data.get("grant_id", ""),
            session_id=data.get("session_id", ""),
            purpose=data.get("purpose", ""),
            choice=data.get("choice", ResearchChoice.EXPLICITLY_REQUESTED),
            allowed_tools=tuple(data.get("allowed_tools", ())),
            created_at=data.get("created_at", ""),
            expires_at=data.get("expires_at"),
        )


@dataclass(frozen=True)
class PublicationAuthorization:
    """Single-use cryptographic authorization token for canonical skill publication."""

    authorization_id: str
    session_id: str
    user_id: str
    payload_hash: str
    scope: str
    disposition: str
    created_at: str = ""
    expires_at: Optional[str] = None
    is_used: bool = False

    def is_valid(self, target_hash: str) -> bool:
        if self.is_used:
            return False
        if not target_hash or self.payload_hash != target_hash:
            return False
        if self.expires_at:
            try:
                exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > exp:
                    return False
            except Exception:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "payload_hash": self.payload_hash,
            "scope": self.scope,
            "disposition": self.disposition,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "is_used": self.is_used,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PublicationAuthorization:
        return cls(
            authorization_id=data.get("authorization_id", ""),
            session_id=data.get("session_id", ""),
            user_id=data.get("user_id", ""),
            payload_hash=data.get("payload_hash", ""),
            scope=data.get("scope", "global"),
            disposition=data.get("disposition", "equip"),
            created_at=data.get("created_at", ""),
            expires_at=data.get("expires_at"),
            is_used=bool(data.get("is_used", False)),
        )


@dataclass(frozen=True)
class QualityGateCheck:
    name: str
    passed: bool
    reason: str = ""


@dataclass(frozen=True)
class QualityGateResult:
    passed: bool
    checks: tuple[QualityGateCheck, ...] = ()
    failures: tuple[str, ...] = ()


def normalize_publication_payload(payload: Any) -> dict[str, Any]:
    """Deterministically normalize skill payload for stable hashing."""
    if hasattr(payload, "skill"):
        skill = payload.skill
    elif isinstance(payload, dict):
        if "skill" in payload and isinstance(payload["skill"], dict):
            skill = payload["skill"]
        else:
            skill = payload
    else:
        skill = payload

    if hasattr(skill, "to_dict"):
        raw = skill.to_dict()
    elif isinstance(skill, dict):
        raw = dict(skill)
    else:
        raw = getattr(skill, "__dict__", {})

    name = str(raw.get("name", "")).strip().casefold()
    domain = str(raw.get("domain", "general")).strip().casefold()
    triggers = tuple(sorted(str(t).strip() for t in raw.get("triggers", ()) if str(t).strip()))
    when_to_use = str(raw.get("when_to_use", "")).strip()
    steps = tuple(str(s).strip() for s in raw.get("steps", ()) if str(s).strip())
    required_tools = tuple(sorted(str(t).strip() for t in raw.get("required_tools", ()) if str(t).strip()))
    forbidden_actions = tuple(sorted(str(a).strip() for a in raw.get("forbidden_actions", ()) if str(a).strip()))
    safety_level = str(raw.get("safety_level", "read_only")).strip().casefold()
    verification = tuple(str(v).strip() for v in raw.get("verification", ()) if str(v).strip())
    scope = str(raw.get("scope", "global")).strip().casefold()
    schema_version = int(raw.get("schema_version", 1))

    research_dict = raw.get("research_metadata")
    if isinstance(research_dict, dict):
        res_choice = research_dict.get("choice", ResearchChoice.NOT_NEEDED)
        res_limitations = tuple(sorted(research_dict.get("limitations", ())))
    elif hasattr(research_dict, "choice"):
        res_choice = getattr(research_dict, "choice", ResearchChoice.NOT_NEEDED)
        res_limitations = tuple(sorted(getattr(research_dict, "limitations", ())))
    else:
        res_choice = ResearchChoice.NOT_NEEDED
        res_limitations = ()

    return {
        "schema_version": schema_version,
        "name": name,
        "domain": domain,
        "scope": scope,
        "triggers": triggers,
        "when_to_use": when_to_use,
        "steps": steps,
        "required_tools": required_tools,
        "forbidden_actions": forbidden_actions,
        "safety_level": safety_level,
        "verification": verification,
        "research_choice": res_choice,
        "research_limitations": res_limitations,
    }


def compute_payload_hash(payload: Any) -> str:
    """Compute deterministic SHA-256 hash for exact-draft publication authorization."""
    import json
    norm = normalize_publication_payload(payload)
    canonical_json = json.dumps(norm, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
