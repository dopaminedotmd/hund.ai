"""ExportFilters — chainable filter builder for trace queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Filter:
    """Chainable filter builder for trace event queries.

    Usage::

        f = Filter().session_id("xyz").event_type("run_completed").risk("safe").limit(100)
        sql, params = f.build()
    """

    run_id: str | None = None
    session_id: str | None = None
    event_type: str | None = None
    actor: str | None = None
    risk: str | None = None
    tool_name: str | None = None
    since: str | None = None
    until: str | None = None
    limit: int = 500
    offset: int = 0

    def with_run(self, run_id: str) -> Filter:
        self.run_id = run_id
        return self

    def with_session(self, session_id: str) -> Filter:
        self.session_id = session_id
        return self

    def with_event_type(self, event_type: str) -> Filter:
        self.event_type = event_type
        return self

    def with_actor(self, actor: str) -> Filter:
        self.actor = actor
        return self

    def with_risk(self, risk: str) -> Filter:
        self.risk = risk
        return self

    def with_tool(self, tool_name: str) -> Filter:
        self.tool_name = tool_name
        return self

    def since_time(self, since: str) -> Filter:
        self.since = since
        return self

    def until_time(self, until: str) -> Filter:
        self.until = until
        return self

    def with_limit(self, limit: int) -> Filter:
        self.limit = limit
        return self

    def with_offset(self, offset: int) -> Filter:
        self.offset = offset
        return self

    def build(self) -> tuple[str, list[Any]]:
        """Build SQL WHERE clause and params from filters.

        Returns:
            Tuple of (where_clause, params_list).
            where_clause is empty string if no filters.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if self.run_id:
            conditions.append("run_id = ?")
            params.append(self.run_id)
        if self.session_id:
            conditions.append("session_id = ?")
            params.append(self.session_id)
        if self.event_type:
            conditions.append("event_type = ?")
            params.append(self.event_type)
        if self.actor:
            conditions.append("actor = ?")
            params.append(self.actor)
        if self.risk:
            conditions.append("risk = ?")
            params.append(self.risk)
        if self.tool_name:
            conditions.append("tool_name = ?")
            params.append(self.tool_name)
        if self.since:
            conditions.append("created_at >= ?")
            params.append(self.since)
        if self.until:
            conditions.append("created_at <= ?")
            params.append(self.until)

        where = ""
        if conditions:
            where = " WHERE " + " AND ".join(conditions)

        return where, params

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for manifest storage."""
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "event_type": self.event_type,
            "actor": self.actor,
            "risk": self.risk,
            "tool_name": self.tool_name,
            "since": self.since,
            "until": self.until,
            "limit": self.limit,
            "offset": self.offset,
        }
