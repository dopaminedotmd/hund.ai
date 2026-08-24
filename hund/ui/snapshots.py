"""Immutable, background-loadable snapshots for fullscreen renderers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StatItem:
    name: str
    abbreviation: str
    value: float | None
    percent: int
    tier: str


@dataclass(frozen=True)
class SpecializationItem:
    name: str
    domain: str
    level: int
    tier: str
    percent: int
    xp: int
    lifecycle_state: str
    vault_state: str
    locked: bool


@dataclass(frozen=True)
class StatsSnapshot:
    version: str
    stats: tuple[StatItem, ...]
    specializations: tuple[SpecializationItem, ...]
    activity: tuple[int, ...]
    activity_dates: tuple[date, ...]
    velocity: tuple[tuple[str, float, bool], ...]
    has_activity: bool


@dataclass(frozen=True)
class SkillItem:
    name: str
    domain: str
    xp: int
    level: int
    tier: str
    percent: int
    lifecycle_state: str
    vault_state: str
    triggers: tuple[str, ...]
    tools: tuple[str, ...]
    safety_level: str
    provenance: tuple[str, ...]
    when_to_use: str


@dataclass(frozen=True)
class SkillsSnapshot:
    equipped: tuple[SkillItem, ...]
    parked: tuple[SkillItem, ...]
    max_active: int


@dataclass(frozen=True)
class ToolItem:
    name: str
    description: str
    parameters: dict[str, Any]
    safety_level: str
    context_mode: str
    category: str | None
    dispatch_description: str | None


@dataclass(frozen=True)
class ToolsSnapshot:
    motor_skills: tuple[str, ...]
    tools: tuple[ToolItem, ...]


@dataclass(frozen=True)
class UsageDay:
    day: date
    prompt_tokens: int
    output_tokens: int
    requests: int
    level: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens


@dataclass(frozen=True)
class SessionUsage:
    prompt_tokens: int | None
    output_tokens: int | None
    requests: int | None

    @property
    def available(self) -> bool:
        return self.prompt_tokens is not None


@dataclass(frozen=True)
class UsageSnapshot:
    days: tuple[UsageDay, ...]
    first_day: date
    last_day: date
    session_id: str | None
    session: SessionUsage


def _package_version() -> str:
    try:
        return version("hund")
    except PackageNotFoundError:
        return "unavailable"


def _home_db(home: Path | None, relative: str) -> Path | None:
    return home / relative if home is not None else None


def collect_stats(*, home: Path | None = None, now: datetime | None = None) -> StatsSnapshot:
    from ..domains import confidence
    from ..domains.xp import get_xp
    from ..skills.vault import SkillVault
    from ..stats.base_stats import compute_all
    from ..stats.velocity import compute_velocity
    from ..store.sqlite import connect
    from .theme import STAT_ABBR, STAT_ORDER

    raw_stats = compute_all(home=home)
    stat_items = tuple(
        StatItem(
            key,
            STAT_ABBR[key],
            raw_stats[key].get("value"),
            int(raw_stats[key].get("progress", 0) or 0),
            str(raw_stats[key].get("tier", "—")),
        )
        for key in STAT_ORDER
    )

    vault = SkillVault(home=home)
    domain_confidence = {
        str(item["domain"]): item
        for item in confidence.list_confidence(_home_db(home, "hund.db"))
    }
    locked_domains: set[str] = set()
    try:
        conn = connect(_home_db(home, "hund.db"))
        rows = conn.execute(
            "SELECT payload_redacted FROM trace_events WHERE event_type='domain_locked'"
        ).fetchall()
        conn.close()
        import json

        for row in rows:
            payload = json.loads(row[0] or "{}")
            if payload.get("domain"):
                locked_domains.add(str(payload["domain"]))
    except Exception:
        pass

    specializations: list[SpecializationItem] = []
    for skill in vault.get_domain_skills():
        xp = get_xp(skill.domain or skill.name, db_path=_home_db(home, "hund.db"))
        conf = domain_confidence.get(skill.domain, {})
        percent = max(int(xp["progress_pct"]), int(conf.get("score", 0) or 0))
        specializations.append(
            SpecializationItem(
                skill.name,
                skill.domain,
                int(xp["level"]),
                str(xp["tier"]),
                min(percent, 100),
                int(xp["xp"]),
                skill.lifecycle_state,
                skill.vault_state,
                bool(skill.user_pinned or skill.domain in locked_domains),
            )
        )

    end = now or datetime.now().astimezone()
    local_tz = end.tzinfo or timezone.utc
    today = end.date()
    dates = tuple(today - timedelta(days=offset) for offset in range(6, -1, -1))
    counts = {day: 0 for day in dates}
    try:
        conn = connect(_home_db(home, "hund.db"))
        rows = conn.execute(
            """SELECT completed_at FROM lifecycle_task_events
               WHERE scope='machine' AND completed_at >= ?""",
            ((end.astimezone(timezone.utc) - timedelta(days=8)).isoformat(),),
        ).fetchall()
        conn.close()
        for row in rows:
            stamp = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
            local_day = stamp.astimezone(local_tz).date()
            if local_day in counts:
                counts[local_day] += 1
    except Exception:
        pass

    velocity = compute_velocity(now=end.astimezone(timezone.utc), home=home)
    velocity_items = tuple(
        (name, float(item["delta"]), bool(item["improving"]))
        for name, item in velocity.items()
    )
    activity = tuple(counts[day] for day in dates)
    return StatsSnapshot(
        _package_version(),
        stat_items,
        tuple(specializations),
        activity,
        dates,
        velocity_items,
        any(activity),
    )


def collect_skills(*, home: Path | None = None) -> SkillsSnapshot:
    from ..domains.xp import get_xp
    from ..skills.vault import SkillVault

    vault = SkillVault(home=home)

    def convert(skill: Any) -> SkillItem:
        xp = get_xp(skill.domain or skill.name, db_path=_home_db(home, "hund.db"))
        provenance = tuple(
            f"{ref.knowledge_id}@{ref.version}" for ref in skill.source_knowledge_refs
        ) + tuple(skill.created_from_event_ids)
        return SkillItem(
            skill.name, skill.domain, int(xp["xp"]), int(xp["level"]),
            str(xp["tier"]), int(xp["progress_pct"]), skill.lifecycle_state,
            skill.vault_state, tuple(skill.triggers), tuple(skill.required_tools),
            skill.safety_level, provenance, skill.when_to_use,
        )

    equipped = tuple(convert(skill) for skill in vault.get_active_skills())
    parked = tuple(convert(skill) for skill in vault.list_vaulted())
    return SkillsSnapshot(equipped, parked, vault.max_active)


def collect_tools() -> ToolsSnapshot:
    from ..skills.loader import load_builtins
    from ..tools.registry import all_tools

    tools = tuple(
        ToolItem(
            tool.name, tool.description, dict(tool.parameters), tool.base_risk,
            tool.context_mode, tool.category, tool.dispatch_description,
        )
        for tool in all_tools()
    )
    return ToolsSnapshot(tuple(skill.name for skill in load_builtins()), tools)


def _month_start(day: date, months_back: int) -> date:
    month_index = day.year * 12 + day.month - 1 - months_back
    return date(month_index // 12, month_index % 12 + 1, 1)


def _local_timezone(now: datetime | None = None):
    current = now or datetime.now().astimezone()
    return current.tzinfo or timezone.utc


def collect_usage(
    *,
    home: Path | None = None,
    session_id: str | None = None,
    now: datetime | None = None,
) -> UsageSnapshot:
    from ..store.sqlite import connect, connect_requests

    local_now = now or datetime.now().astimezone()
    tz = _local_timezone(local_now)
    first = _month_start(local_now.date(), 6)
    last = local_now.date()
    daily: dict[date, list[int]] = {}
    request_db = _home_db(home, "logs/requests.db")
    try:
        conn = connect_requests(request_db)
        rows = conn.execute(
            """SELECT created_at, COALESCE(prompt_tokens,0),
                      COALESCE(completion_tokens,0), run_id
               FROM requests ORDER BY created_at"""
        ).fetchall()
        conn.close()
    except Exception:
        rows = []

    for created_at, prompt, output, _run_id in rows:
        try:
            stamp = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            local_day = stamp.astimezone(tz).date()
        except Exception:
            continue
        if first <= local_day <= last:
            values = daily.setdefault(local_day, [0, 0, 0])
            values[0] += int(prompt or 0)
            values[1] += int(output or 0)
            values[2] += 1

    positives = sorted(v[0] + v[1] for v in daily.values() if v[0] + v[1] > 0)
    thresholds: list[int] = []
    if positives:
        thresholds = [
            positives[min(len(positives) - 1, (len(positives) * q - 1) // 4)]
            for q in (1, 2, 3)
        ]

    def level(total: int) -> int:
        if total <= 0:
            return 0
        return 1 + sum(total > threshold for threshold in thresholds)

    days: list[UsageDay] = []
    cursor = first
    while cursor <= last:
        prompt, output, count = daily.get(cursor, [0, 0, 0])
        days.append(UsageDay(cursor, prompt, output, count, level(prompt + output)))
        cursor += timedelta(days=1)

    session = SessionUsage(None, None, None)
    if session_id:
        try:
            core = connect(_home_db(home, "hund.db"))
            run_rows = core.execute(
                "SELECT DISTINCT run_id FROM trace_events WHERE session_id=?",
                (session_id,),
            ).fetchall()
            core.close()
            run_ids = [str(row[0]) for row in run_rows if row[0]]
            if run_ids:
                req = connect_requests(request_db)
                placeholders = ",".join("?" for _ in run_ids)
                row = req.execute(
                    f"""SELECT COALESCE(SUM(prompt_tokens),0),
                               COALESCE(SUM(completion_tokens),0), COUNT(*)
                        FROM requests WHERE run_id IN ({placeholders})""",
                    run_ids,
                ).fetchone()
                req.close()
                session = SessionUsage(int(row[0]), int(row[1]), int(row[2]))
        except Exception:
            pass
    return UsageSnapshot(tuple(days), first, last, session_id, session)
