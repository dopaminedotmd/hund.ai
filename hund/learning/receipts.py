"""Public progress receipts and human-readable formatting without internal IDs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PublicProgressReceipt:
    system: str  # "skill" | "domain" | "base_stat"
    entity: str  # e.g. "marketing", "python", "Endurance"
    delta_xp: int
    new_total: int | float
    new_tier: str
    reason: str
    timestamp: str


def format_public_receipt(receipt: PublicProgressReceipt) -> str:
    """Format a PublicProgressReceipt into clean, non-technical UI text."""
    entity_padded = f"{receipt.entity:<15}"

    if receipt.system == "skill":
        return f"{entity_padded} +{receipt.delta_xp} skill XP · {receipt.reason}"

    if receipt.system == "domain":
        return f"{entity_padded} +{receipt.delta_xp} domain XP · {receipt.reason}"

    if receipt.system == "base_stat":
        return f"{entity_padded} improved to {int(receipt.new_total)}% · {receipt.reason}"

    return f"{entity_padded} +{receipt.delta_xp} XP · {receipt.reason}"
