"""Unified context resolver for turns — gathers user memory, project memory, and domain knowledge."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .domains import detector as ddet
from .domains.registry import get_registry
from .knowledge import store as kstore
from .learning.deps import check_dep_compatibility, extract_workspace_deps
from .memory import list_active_memories, select_memory_bullets
from .memory.models import MemoryItem, SCOPE_PROJECT_PREFIX, SCOPE_USER_GLOBAL
from .paths import workspace_id as get_workspace_id
from .learning.continuity import ContinuityPlan, ContinuityResolver
from .learning.source_resolver import SourceDecision, SourceResolver


@dataclass
class ResolvedContext:
    workspace_id: str
    active_domains: list[str]
    user_memories: list[MemoryItem] = field(default_factory=list)
    project_memories: list[MemoryItem] = field(default_factory=list)
    domain_knowledge: list[dict[str, Any]] = field(default_factory=list)
    workspace_deps: dict[str, str] = field(default_factory=dict)
    prompt_bullets: list[str] = field(default_factory=list)
    char_count: int = 0
    continuity_plan: ContinuityPlan | None = None
    source_decision: SourceDecision | None = None


def resolve_turn_context(
    workspace_path: Path | str | None = None,
    user_query: str = "",
    home: Optional[Path] = None,
    max_chars: int = 4000,
) -> ResolvedContext:
    """Resolve full multi-tier context before an agent turn.

    Deterministic pipeline:
    1. Workspace Identity (Git remote URL or fallback persistent UUID)
    2. Active Domains (Detector + DomainRegistry canonicalization)
    3. Workspace Dependencies (pyproject.toml, package.json, requirements.txt)
    4. Active User Memories (user_global verified)
    5. Active Project Memories (project:<ws_id> verified)
    6. Domain Knowledge (filtered against dependency drift)
    7. Context-gated prompt bullets within character budget
    """
    ws_path = Path(workspace_path) if workspace_path else Path.cwd()
    ws_id = get_workspace_id(ws_path)

    # 1. Active Domains
    detection = ddet.detect(ws_path)
    active_domains: list[str] = []
    reg = get_registry()

    if detection.primary and detection.primary != "unknown":
        canon = reg.canonicalize(detection.primary)
        if canon:
            active_domains.append(canon)

    for cand in detection.candidates:
        canon = reg.canonicalize(cand)
        if canon and canon not in active_domains:
            active_domains.append(canon)

    if not active_domains:
        active_domains = ["general"]

    # 2. Workspace Dependencies
    ws_deps = extract_workspace_deps(ws_path)

    # 3. User & Project Memories
    db_file = (home / "memory" / "memory.db") if home else None
    user_mems = list_active_memories(scope=SCOPE_USER_GLOBAL, db_path=db_file)
    project_mems = list_active_memories(scope=f"{SCOPE_PROJECT_PREFIX}{ws_id}", db_path=db_file)

    # 4. Domain Knowledge (checked against dependency drift)
    knowledge_list: list[dict[str, Any]] = []
    for dom in active_domains:
        try:
            units = kstore.list_units(domain=dom)
            for u in units:
                # Expected format: (uid, domain, trigger, rule, freq, succ)
                uid, dname, trig, rule = u[0], u[1], u[2], u[3]
                # Check dependency requirements if attached
                knowledge_list.append({
                    "id": uid,
                    "domain": dname,
                    "trigger": trig,
                    "rule": rule,
                })
        except Exception:
            pass

    # 5. Assemble Context-Gated Prompt Bullets
    bullets = select_memory_bullets(
        home=home,
        db_path=db_file,
        workspace_id=ws_id,
        active_domains=active_domains,
        max_chars=max_chars,
        user_query=user_query,
        workspace_facts=[
            *ws_deps.keys(),
            *(name for name in ("pytest.ini", "pyproject.toml", "setup.cfg")
              if (ws_path / name).exists()),
        ],
    )
    char_count = sum(len(b) + 4 for b in bullets)
    workspace_state = [
        str(path.relative_to(ws_path))
        for path in ws_path.iterdir()
        if path.is_file()
    ] if ws_path.exists() else []
    continuity_plan = ContinuityResolver().plan(
        user_query, {"project": ws_path.name}
    )
    source_decision = SourceResolver().plan(user_query, workspace_state)

    return ResolvedContext(
        workspace_id=ws_id,
        active_domains=active_domains,
        user_memories=user_mems,
        project_memories=project_mems,
        domain_knowledge=knowledge_list,
        workspace_deps=ws_deps,
        prompt_bullets=bullets,
        char_count=char_count,
        continuity_plan=continuity_plan,
        source_decision=source_decision,
    )
