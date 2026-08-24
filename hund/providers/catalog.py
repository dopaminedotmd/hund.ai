"""Truthful model presets and atomic runtime switching."""
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from ..secrets import load_api_key


@dataclass(frozen=True)
class ModelOption:
    provider_id: str
    provider_name: str
    model_id: str
    base_url: str
    context_window: int
    credential_id: str
    description: str
    is_local: bool = False
    env_name: str = "HUND_API_KEY"


MODEL_OPTIONS: tuple[ModelOption, ...] = (
    ModelOption(
        "deepseek", "DeepSeek", "deepseek-chat", "https://api.deepseek.com",
        64_000, "deepseek", "Fast and token-efficient", env_name="DEEPSEEK_API_KEY",
    ),
    ModelOption(
        "deepseek", "DeepSeek", "deepseek-reasoner", "https://api.deepseek.com",
        64_000, "deepseek", "Reasoning model", env_name="DEEPSEEK_API_KEY",
    ),
    ModelOption(
        "openrouter", "OpenRouter", "nvidia/nemotron-3.5-lightning:free",
        "https://openrouter.ai/api/v1", 256_000, "openrouter",
        "Free Nemotron preset", env_name="OPENROUTER_API_KEY",
    ),
    ModelOption(
        "local", "Local", "local", "http://127.0.0.1", 32_000, "local",
        "Local GGUF model", is_local=True, env_name="",
    ),
)


def custom_model(
    provider_id: str,
    base_url: str,
    model_id: str,
    context_window: int,
    *,
    credential_id: str | None = None,
) -> ModelOption:
    """Build a validated custom OpenAI-compatible option."""
    provider = provider_id.strip().lower()
    url = base_url.strip().rstrip("/")
    model = model_id.strip()
    if not provider or not url.startswith(("http://", "https://")) or not model:
        raise ValueError("Provider, HTTP(S) base URL, and model ID are required.")
    if not 1_024 <= int(context_window) <= 10_000_000:
        raise ValueError("Context window must be between 1,024 and 10,000,000.")
    return ModelOption(
        provider, provider_id.strip(), model, url, int(context_window),
        credential_id or provider, "Custom OpenAI-compatible model",
        env_name=f"{provider.upper().replace('-', '_')}_API_KEY",
    )


def credential_for(option: ModelOption) -> str:
    """Resolve credentials with HUND_API_KEY as the legacy top-priority override."""
    legacy = os.environ.get("HUND_API_KEY", "")
    if legacy:
        return legacy
    return load_api_key(option.env_name or "__HUND_LOCAL_NO_KEY__", option.credential_id)


def option_ready(option: ModelOption) -> bool:
    if not option.is_local:
        return bool(credential_for(option))
    try:
        from ..local.engine import LocalEngine

        engine = LocalEngine()
        return engine.model_path is not None and engine.is_running
    except Exception:
        return False


def active_option(cfg: Any) -> ModelOption:
    """Return the configured option even when it is a custom model."""
    for option in MODEL_OPTIONS:
        if (
            option.model_id == cfg.provider.model
            and option.base_url.rstrip("/") == cfg.provider.base_url.rstrip("/")
        ):
            return option
    return custom_model(
        getattr(cfg.provider, "provider_id", "custom"),
        cfg.provider.base_url,
        cfg.provider.model,
        getattr(cfg.provider, "context_window", 64_000),
        credential_id=getattr(cfg.provider, "credential_id", "custom"),
    )


def activate_model(rt: Any, option: ModelOption) -> tuple[bool, str]:
    """Create a candidate client first, then atomically update runtime and config."""
    old_client = rt.client
    old_key = getattr(rt, "key", "")
    old_values = (
        rt.cfg.provider.base_url,
        rt.cfg.provider.model,
        rt.cfg.provider.provider_id,
        rt.cfg.provider.credential_id,
        rt.cfg.provider.context_window,
        rt.cfg.provider.api_key_env,
    )
    try:
        if option.is_local:
            from ..local.engine import LocalEngine
            from .local import LocalProvider

            engine = getattr(old_client, "_engine", None) or LocalEngine()
            if engine.model_path is None or not engine.is_running:
                return False, "No running local model was found."
            candidate = LocalProvider(engine=engine, model=option.model_id)
            key = "__local__"
        else:
            from .openai_compatible import OpenAICompatibleClient

            key = credential_for(option)
            if not key:
                return False, (
                    f"Missing credential for {option.provider_name}. "
                    f"Set {option.env_name or 'HUND_API_KEY'} or press [k]."
                )
            candidate = OpenAICompatibleClient(option.base_url, key, option.model_id)

        rt.client = candidate
        rt.key = key
        rt.cfg.provider.base_url = option.base_url
        rt.cfg.provider.model = option.model_id
        rt.cfg.provider.provider_id = option.provider_id
        rt.cfg.provider.credential_id = option.credential_id
        rt.cfg.provider.context_window = option.context_window
        rt.cfg.provider.api_key_env = option.env_name or "HUND_API_KEY"
        rt.cfg.save()
        return True, f"Active model: {option.model_id}"
    except Exception:
        rt.client = old_client
        rt.key = old_key
        (
            rt.cfg.provider.base_url,
            rt.cfg.provider.model,
            rt.cfg.provider.provider_id,
            rt.cfg.provider.credential_id,
            rt.cfg.provider.context_window,
            rt.cfg.provider.api_key_env,
        ) = old_values
        return False, "Model switch failed; the previous provider remains active."
