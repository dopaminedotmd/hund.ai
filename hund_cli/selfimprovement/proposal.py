"""Proposal — deklarativt förbättringsförslag från gaps. Ej exekverbar kod."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..learning.redactor import redact_text
from ..skills.model import Skill
from ..skills.validator import validate
from ..store.sqlite import connect

# TCB-skydd: change_type tvingas deklarativ. Core-kod får aldrig föreslås.
ALLOWED_CHANGE_TYPES = {"runtime_policy", "skill", "hundk", "prompt", "test"}

# Change-types som kräver rollback_note (alla write-nära typer).
WRITE_CHANGE_TYPES = {"runtime_policy", "skill", "hundk"}

# Fas 9.6: giltiga statusövergångar. "applied" stänger self-improvement-loopen.
VALID_STATUSES = {"proposed", "approved", "rejected", "applied"}

# Mönster för råa filinnehåll — blockeras ur förslag.
_RAW_CONTENT_PATTERNS = [
    re.compile(r"^(?:content|file_content|raw_content)$", re.IGNORECASE),
]
_RAW_CONTENT_MAX_CHARS = 500  # Fält som är längre än så misstänks vara rådata

_COLS = [
    "id", "created_at", "title", "problem", "proposed_change",
    "change_type", "risk", "tests_needed", "related_gaps", "status",
    "verification_required", "rollback_note", "raw_summary",
]


@dataclass
class Proposal:
    id: str
    created_at: str
    title: str
    problem: str
    proposed_change: str
    change_type: str
    risk: str
    tests_needed: str
    related_gaps: list
    status: str = "proposed"
    # Fas 8 — v1.5 fält
    verification_required: bool = True  # alltid True, kan inte sättas False
    rollback_note: str = ""             # obligatoriskt för write-nära change_types
    # Fas 9.6 — LLM:ens fulla JSON-svar (redakterat), för apply --apply.
    raw_summary: str = ""

    def as_markdown(self) -> str:
        rollback_section = (
            f"\n## Rollback\n{self.rollback_note}\n"
            if self.rollback_note
            else "\n## Rollback\n*(ej angiven)*\n"
        )
        verification = "✅ krävs" if self.verification_required else "⚠️ ej satt"
        return (
            f"# Proposal {self.id[:8]} — {self.title}\n\n"
            f"status: **{self.status}** · type: `{self.change_type}` · risk: {self.risk}"
            f" · verifiering: {verification}\n\n"
            f"## Problem\n{self.problem}\n\n"
            f"## Föreslagen ändring ({self.change_type})\n{self.proposed_change}\n\n"
            f"## Tester som krävs\n{self.tests_needed or '(ingen)'}\n\n"
            f"## Relaterade gaps\n{', '.join(self.related_gaps) or '(ingen)'}\n"
            + rollback_section
        )


def create(p: Proposal) -> None:
    conn = connect()
    conn.execute(
        f"INSERT INTO proposals ({','.join(_COLS)}) VALUES ({','.join('?' * len(_COLS))})",
        (
            p.id, p.created_at, p.title, p.problem, p.proposed_change,
            p.change_type, p.risk, p.tests_needed, json.dumps(p.related_gaps), p.status,
            int(p.verification_required), p.rollback_note, p.raw_summary,
        ),
    )
    conn.commit()
    conn.close()


def list_proposals(status: str | None = None) -> list[Proposal]:
    conn = connect()
    if status:
        rows = conn.execute(
            "SELECT * FROM proposals WHERE status=? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM proposals ORDER BY created_at DESC").fetchall()
    conn.close()
    return [_row(r) for r in rows]


def get(pid_prefix: str) -> Proposal | None:
    conn = connect()
    rows = conn.execute("SELECT * FROM proposals WHERE id LIKE ?", (pid_prefix + "%",)).fetchall()
    conn.close()
    return _row(rows[0]) if rows else None


def set_status(pid_prefix: str, status: str) -> int:
    """Markerar status i DB. Applicerar ALDRIG ändringen på systemet.

    Fas 9.6: accepterar "applied" (status sätts av apply_skill_proposal-vägen).
    Ogiltig status → 0 rader uppdaterade (inget kastas).
    """
    if status not in VALID_STATUSES:
        return 0
    conn = connect()
    cur = conn.execute("UPDATE proposals SET status=? WHERE id LIKE ?", (status, pid_prefix + "%"))
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


def _is_raw_file_content(name: str, value: str) -> bool:
    """Returnerar True om ett fält misstänks innehålla rå fildata."""
    for pat in _RAW_CONTENT_PATTERNS:
        if pat.match(name):
            return True
    # Heuristik: mycket långa fält med radbrytningar är sannolikt råinnehåll
    if len(value) > _RAW_CONTENT_MAX_CHARS and "\n" in value:
        return True
    return False


def build_from_gaps(gaps: list, llm_summary: dict) -> "Proposal":
    """gaps: list of gap-rows; llm_summary: dikterade fält från LLM."""
    ct = llm_summary.get("change_type", "runtime_policy")
    if ct not in ALLOWED_CHANGE_TYPES:  # TCB-skydd: tvinga deklarativ
        ct = "runtime_policy"

    def safe_field(name: str, default: str = "") -> str:
        raw = str(llm_summary.get(name, default))
        # Fas 8: blockera råa filinnehåll — ersätt med placeholder
        if _is_raw_file_content(name, raw):
            return "[REDACTED: raw file content not allowed in proposals]"
        return redact_text(raw).text

    # rollback_note är obligatoriskt för write-nära typer
    rollback_raw = str(llm_summary.get("rollback_note", ""))
    rollback = redact_text(rollback_raw).text if rollback_raw else ""

    # Fas 9.6: spara LLM:ens fulla JSON (redakterat) så apply --apply kan bygga
    # skill-filen senare. Redactera alla skalärsträngar — konsekvent med modulens
    # privatmodell (LLM kan ekotillbaka hemligheter).
    raw_summary = json.dumps(_redact_summary(llm_summary), ensure_ascii=False)

    return Proposal(
        id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
        title=safe_field("title", "(ingen titel)"),
        problem=safe_field("problem"),
        proposed_change=safe_field("proposed_change"),
        change_type=ct,
        risk=safe_field("risk", "unknown"),
        tests_needed=safe_field("tests_needed"),
        related_gaps=[g[0] for g in gaps],
        verification_required=True,  # alltid obligatorisk
        rollback_note=rollback,
        raw_summary=raw_summary,
    )


def _redact_summary(obj):
    """Redaktera alla skalärsträngar i en godtycklig dict/list (rekursivt)."""
    if isinstance(obj, str):
        return redact_text(obj).text
    if isinstance(obj, list):
        return [_redact_summary(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _redact_summary(v) for k, v in obj.items()}
    return obj


def _row(r) -> Proposal:
    # Hantera både gamla rader (utan de nya kolumnerna) och nya
    if len(r) >= len(_COLS):
        d = dict(zip(_COLS, r))
    else:
        # Bakåtkompatibilitet: gamla rader saknar verification_required + rollback_note
        old_cols = _COLS[:len(r)]
        d = dict(zip(old_cols, r))
    try:
        d["related_gaps"] = json.loads(d.get("related_gaps") or "[]")
    except json.JSONDecodeError:
        d["related_gaps"] = []
    d.setdefault("verification_required", True)
    d.setdefault("rollback_note", "")
    d.setdefault("raw_summary", "")
    # Konvertera int → bool för verification_required
    d["verification_required"] = bool(d["verification_required"])
    return Proposal(**d)


# ---------------------------------------------------------------------- #
# Fas 9.6 — stäng self-improvement-loopen: approved skill → skill-fil    #
# ---------------------------------------------------------------------- #

# risk → safety_level. Mänskligt godkänd skill → status "active".
_RISK_TO_SAFETY = {
    "low": "confirm",
    "medium": "confirm",
    "high": "confirm_for_write",
}


def build_skill_from_proposal(proposal: Proposal, raw_summary: dict) -> Skill | None:
    """Extrahera en Skill ur en godkänd proposal.

    Returnerar None om change_type != "skill" eller skill_name saknas.
    Returnerar en (ev. ofullständig) Skill annars — validate() fångar saknade
    forbidden_actions/verification, så anroparen kan rapportera felen.
    """
    if proposal.change_type != "skill":
        return None

    name = str(raw_summary.get("skill_name", "")).strip()
    if not name:
        return None

    risk = str(raw_summary.get("risk") or proposal.risk or "medium").strip().lower()
    safety = str(
        raw_summary.get("skill_safety_level") or _RISK_TO_SAFETY.get(risk, "confirm")
    ).strip()

    when = (
        str(raw_summary.get("skill_when_to_use", "")).strip()
        or proposal.proposed_change
        or proposal.problem
    )

    def _strs(key: str) -> tuple[str, ...]:
        v = raw_summary.get(key)
        if isinstance(v, list):
            return tuple(str(x) for x in v if str(x).strip())
        if isinstance(v, str) and v.strip():
            return (v.strip(),)
        return ()

    return Skill(
        schema_version=1,
        name=name,
        domain=str(raw_summary.get("skill_domain") or "general").strip(),
        status="active",
        triggers=_strs("skill_triggers"),
        when_to_use=when,
        steps=_strs("skill_steps"),
        required_tools=_strs("skill_required_tools"),
        forbidden_actions=_strs("skill_forbidden"),
        safety_level=safety,
        verification=_strs("skill_verification"),
        examples=(),
    )


def apply_skill_proposal(proposal: Proposal, raw_summary: dict) -> tuple[bool, str]:
    """Validera + spara skill till brain/skills/<name>.json.

    Return (ok, meddelande). Vid ok innehåller meddelandet filens sökväg.
    """
    from ..paths import brain_skills_dir

    skill = build_skill_from_proposal(proposal, raw_summary)
    if skill is None:
        return (
            False,
            "kan ej bygga skill: change_type är inte 'skill' eller skill_name saknas",
        )

    errors = validate(skill)
    if errors:
        return (False, "ogiltig skill: " + "; ".join(errors))

    target_dir = brain_skills_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{skill.name}.json"
    path.write_text(
        json.dumps(skill.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Rundresa: läs tillbaka och validera igen.
    try:
        reread = Skill.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        return (False, f"rundresa misslyckades (läs-tillbaka): {e}")
    if validate(reread):
        return (False, "rundresa misslyckades: omläst skill ogiltig")

    return (True, str(path))

