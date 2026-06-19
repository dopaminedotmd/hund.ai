"""API-nyckelhantering — säker lagring via miljövariabler."""
from __future__ import annotations

import os


def load_api_key(env_name: str = "HUND_API_KEY") -> str:
    """Läs API-nyckel från miljövariabel."""
    return os.environ.get(env_name, "")


def save_api_key(value: str) -> bool:
    """Spara API-nyckel (avaktiverad). Returnerar False."""
    return False


def delete_api_key() -> bool:
    """Ta bort API-nyckel (avaktiverad). Returnerar False."""
    return False
