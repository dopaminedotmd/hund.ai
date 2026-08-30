"""Independent, fail-closed feature flags for the specialization runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SpecializationFeatureFlags:
    read_enabled: bool = False
    proposals_enabled: bool = False
    activation_enabled: bool = False
    progression_enabled: bool = False


def feature_flags_from_mapping(values: Mapping[str, Any]) -> SpecializationFeatureFlags:
    def enabled(key: str) -> bool:
        return values.get(key) is True

    return SpecializationFeatureFlags(
        read_enabled=enabled("specializations_read_enabled"),
        proposals_enabled=enabled("specializations_proposals_enabled"),
        activation_enabled=enabled("specializations_activation_enabled"),
        progression_enabled=enabled("specializations_progression_enabled"),
    )
