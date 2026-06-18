"""API-nyckelhantering — säker lagring.

Prioritet: OS-nyckelring (Windows DPAPI / Credential Manager via `keyring`),
fallback till miljövariabel. Nyckel sparas ALDRIG i config.json eller repo.
"""
from __future__ import annotations

import os

SERVICE = "hund"
USERNAME = "api_key"


def load_api_key(env_name: str = "HUND_API_KEY") -> str:
    env = os.environ.get(env_name, "")
    if env:
        return env
    try:
        import keyring

        return keyring.get_password(SERVICE, USERNAME) or ""
    except Exception:
        # keyring inte tillgängligt/bakend saknas -> env-krav kvarstår
        return ""


def save_api_key(value: str) -> bool:
    """Spara till OS-nyckelring. Returnerar True vid framgång."""
    try:
        import keyring

        keyring.set_password(SERVICE, USERNAME, value)
        return True
    except Exception:
        return False


def delete_api_key() -> bool:
    try:
        import keyring

        keyring.delete_password(SERVICE, USERNAME)
        return True
    except Exception:
        return False
