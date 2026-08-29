"""Provenance-aware research packets and SQLite storage."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Optional

from ..store.sqlite import connect
from .source_hierarchy import SourceTier


@dataclass(frozen=True)
class ResearchSourceRecord:
    url: str
    domain: str
    title: str
    retrieved_at: str
    source_tier: str
    content_hash: str
    author: str = ""
    license: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchSourceRecord:
        return cls(**data)


@dataclass(frozen=True)
class ResearchClaim:
    claim_id: str
    text: str
    source_urls: tuple[str, ...]
    corroboration_count: int
    confidence: float
    freshness_timestamp: str
    is_procedural: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source_urls"] = list(self.source_urls)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchClaim:
        d = dict(data)
        d["source_urls"] = tuple(d.get("source_urls", []))
        return cls(**d)


@dataclass(frozen=True)
class ResearchPacket:
    packet_id: str
    need_id: str
    capability_id: str
    domain: str
    canonical_queries: tuple[str, ...]
    sources: tuple[ResearchSourceRecord, ...]
    claims: tuple[ResearchClaim, ...]
    conflicts: tuple[str, ...]
    freshness_window_days: int
    coverage_score: float
    safety_scan_passed: bool
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "need_id": self.need_id,
            "capability_id": self.capability_id,
            "domain": self.domain,
            "canonical_queries": list(self.canonical_queries),
            "sources": [s.to_dict() for s in self.sources],
            "claims": [c.to_dict() for c in self.claims],
            "conflicts": list(self.conflicts),
            "freshness_window_days": self.freshness_window_days,
            "coverage_score": self.coverage_score,
            "safety_scan_passed": self.safety_scan_passed,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchPacket:
        return cls(
            packet_id=data["packet_id"],
            need_id=data["need_id"],
            capability_id=data["capability_id"],
            domain=data["domain"],
            canonical_queries=tuple(data.get("canonical_queries", [])),
            sources=tuple(ResearchSourceRecord.from_dict(s) for s in data.get("sources", [])),
            claims=tuple(ResearchClaim.from_dict(c) for c in data.get("claims", [])),
            conflicts=tuple(data.get("conflicts", [])),
            freshness_window_days=int(data.get("freshness_window_days", 90)),
            coverage_score=float(data.get("coverage_score", 1.0)),
            safety_scan_passed=bool(data.get("safety_scan_passed", True)),
            status=data.get("status", "synthesized"),
        )


class ResearchPacketStore:
    """Durable SQLite storage for research packets."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else None
        self._ensure_table()

    def _ensure_table(self) -> None:
        conn = connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS research_packets (
                    packet_id TEXT PRIMARY KEY,
                    need_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    status TEXT NOT NULL,
                    safety_scan_passed INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_research_packets_cap ON research_packets(capability_id)"
            )
            conn.commit()
        finally:
            conn.close()

    def save_packet(self, packet: ResearchPacket) -> None:
        conn = connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            payload = json.dumps(packet.to_dict())
            conn.execute(
                """INSERT OR REPLACE INTO research_packets
                (packet_id, need_id, capability_id, domain, status, safety_scan_passed, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    packet.packet_id,
                    packet.need_id,
                    packet.capability_id,
                    packet.domain,
                    packet.status,
                    1 if packet.safety_scan_passed else 0,
                    payload,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_packet(self, packet_id: str) -> Optional[ResearchPacket]:
        conn = connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT payload_json FROM research_packets WHERE packet_id = ?",
                (packet_id,),
            ).fetchone()
            if not row:
                return None
            data = json.loads(row[0])
            return ResearchPacket.from_dict(data)
        finally:
            conn.close()
