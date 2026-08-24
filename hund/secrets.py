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


def load_api_key(
    env_name: str = "HUND_API_KEY",
    credential_id: str = DEFAULT_CREDENTIAL_ID,
) -> str:
    """Load from the environment first, then the provider-specific OS vault entry."""
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
    if env_name != "HUND_API_KEY":
        legacy = os.environ.get("HUND_API_KEY", "")
        if legacy:
            return legacy
    try:
        import keyring

        target_cred = _credential_id_for(env_name, credential_id)
        if target_cred != DEFAULT_CREDENTIAL_ID:
            val_default = keyring.get_password(SERVICE_NAME, DEFAULT_CREDENTIAL_ID)
            if val_default:
                return val_default
    except Exception:
        pass
    return ""


def save_api_key(
    value: str,
    credential_id: str = DEFAULT_CREDENTIAL_ID,
) -> bool:
    """Store a credential in the OS vault; never fall back to a plaintext file."""
    if not value:
        return False
    try:
        import keyring

        keyring.set_password(SERVICE_NAME, credential_id, value)
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
