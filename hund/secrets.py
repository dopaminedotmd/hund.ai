"""API credentials with environment-first, fail-closed OS vault storage."""
from __future__ import annotations

import os


SERVICE_NAME = "hund.ai"
DEFAULT_CREDENTIAL_ID = "deepseek"


def _credential_id_for(env_name: str, credential_id: str) -> str:
    """Infer the provider for legacy callers that only pass an env name."""
    if credential_id != DEFAULT_CREDENTIAL_ID:
        return credential_id
    return {
        "OPENROUTER_API_KEY": "openrouter",
        "DEEPSEEK_API_KEY": "deepseek",
    }.get(env_name, credential_id)


def get_credential_status(
    credential_id: str = DEFAULT_CREDENTIAL_ID,
    env_name: str = "HUND_API_KEY",
    active_credential_id: str | None = None,
) -> tuple[str, str]:
    """Return status ("environment" | "configured" | "missing", info_detail)."""
    if env_name and env_name != "HUND_API_KEY" and os.environ.get(env_name):
        return ("environment", env_name)
    try:
        import keyring

        target_cred = _credential_id_for(env_name, credential_id)
        val = keyring.get_password(SERVICE_NAME, target_cred)
        if val:
            return ("configured", "")
    except Exception:
        pass
    # Legacy HUND_API_KEY only satisfies the explicitly active credential_id
    if os.environ.get("HUND_API_KEY"):
        if active_credential_id and credential_id == active_credential_id:
            return ("environment", "HUND_API_KEY")
    return ("missing", "")


def load_api_key(
    env_name: str = "HUND_API_KEY",
    credential_id: str = DEFAULT_CREDENTIAL_ID,
    active_credential_id: str | None = None,
) -> str:
    """Load from the environment first, then the provider-specific OS vault entry."""
    if env_name and env_name != "HUND_API_KEY":
        value = os.environ.get(env_name, "")
        if value:
            return value
    try:
        import keyring

        target_cred = _credential_id_for(env_name, credential_id)
        val = keyring.get_password(SERVICE_NAME, target_cred)
        if val:
            return val
    except Exception:
        pass
    if active_credential_id and credential_id == active_credential_id:
        legacy = os.environ.get("HUND_API_KEY", "")
        if legacy:
            return legacy
    return ""


def save_api_key(
    value: str,
    credential_id: str = DEFAULT_CREDENTIAL_ID,
) -> bool:
    """Store a credential in the OS vault; never fall back to a plaintext file."""
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        return False
    try:
        import keyring

        keyring.set_password(SERVICE_NAME, credential_id, cleaned)
        return True
    except Exception:
        return False


def delete_api_key(credential_id: str = DEFAULT_CREDENTIAL_ID) -> bool:
    """Delete a provider credential from the OS vault, failing closed."""
    try:
        import keyring

        keyring.delete_password(SERVICE_NAME, credential_id)
        return True
    except Exception:
        return False
