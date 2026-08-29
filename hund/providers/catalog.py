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


@dataclass(frozen=True)
class ProviderPreset:
    provider_id: str
    name: str
    description: str
    base_url: str
    default_models: tuple[str, ...]
    context_window: int
    credential_id: str
    env_name: str


PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        "deepseek", "DeepSeek", "Official API (v4-flash, v4-pro, chat, reasoner)",
        "https://api.deepseek.com", (
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "deepseek-v4-flash-vision-exp",
            "deepseek-chat",
            "deepseek-reasoner",
        ),
        1_000_000, "deepseek", "DEEPSEEK_API_KEY",
    ),
    ProviderPreset(
        "openrouter", "OpenRouter", "Access 100+ models with 1 key",
        "https://openrouter.ai/api/v1", (
            "anthropic/claude-3.5-sonnet",
            "deepseek/deepseek-r1",
            "google/gemini-2.0-flash-exp:free",
            "meta-llama/llama-3.3-70b-instruct",
            "nvidia/nemotron-3.5-lightning:free",
        ),
        256_000, "openrouter", "OPENROUTER_API_KEY",
    ),
    ProviderPreset(
        "openai", "OpenAI", "Official API (gpt-4o, gpt-4o-mini, o3-mini, o1)",
        "https://api.openai.com/v1", (
            "gpt-4o",
            "gpt-4o-mini",
            "o3-mini",
            "o1",
            "gpt-4.5-preview",
        ),
        128_000, "openai", "OPENAI_API_KEY",
    ),
    ProviderPreset(
        "groq", "Groq", "Ultra-fast open models (Llama 3.3, DeepSeek R1)",
        "https://api.groq.com/openai/v1", (
            "llama-3.3-70b-versatile",
            "deepseek-r1-distill-llama-70b",
            "mixtral-8x7b-32768",
        ),
        128_000, "groq", "GROQ_API_KEY",
    ),
    ProviderPreset(
        "custom", "Custom Endpoint", "Custom OpenAI-compatible URL",
        "", (), 32_000, "custom", "HUND_API_KEY",
    ),
)


MODEL_OPTIONS: tuple[ModelOption, ...] = (
    ModelOption(
        "deepseek", "DeepSeek", "deepseek-v4-flash", "https://api.deepseek.com",
        1_000_000, "deepseek", "Fast and token-efficient (default)", env_name="DEEPSEEK_API_KEY",
    ),
    ModelOption(
        "deepseek", "DeepSeek", "deepseek-v4-pro", "https://api.deepseek.com",
        1_000_000, "deepseek", "High-precision model", env_name="DEEPSEEK_API_KEY",
    ),
    ModelOption(
        "deepseek", "DeepSeek", "deepseek-v4-flash-vision-exp", "https://api.deepseek.com",
        1_000_000, "deepseek", "Multimodal vision model", env_name="DEEPSEEK_API_KEY",
    ),
    ModelOption(
        "deepseek", "DeepSeek", "deepseek-chat", "https://api.deepseek.com",
        1_000_000, "deepseek", "Fast chat model", env_name="DEEPSEEK_API_KEY",
    ),
    ModelOption(
        "deepseek", "DeepSeek", "deepseek-reasoner", "https://api.deepseek.com",
        1_000_000, "deepseek", "Reasoning model", env_name="DEEPSEEK_API_KEY",
    ),
    # OpenAI suite
    ModelOption(
        "openai", "OpenAI", "gpt-4o", "https://api.openai.com/v1",
        128_000, "openai", "OpenAI GPT-4o flagship", env_name="OPENAI_API_KEY",
    ),
    ModelOption(
        "openai", "OpenAI", "gpt-4o-mini", "https://api.openai.com/v1",
        128_000, "openai", "Fast and affordable GPT-4o-mini", env_name="OPENAI_API_KEY",
    ),
    ModelOption(
        "openai", "OpenAI", "o3-mini", "https://api.openai.com/v1",
        200_000, "openai", "OpenAI o3-mini reasoning", env_name="OPENAI_API_KEY",
    ),
    ModelOption(
        "openai", "OpenAI", "o1", "https://api.openai.com/v1",
        200_000, "openai", "OpenAI o1 reasoning flagship", env_name="OPENAI_API_KEY",
    ),
    ModelOption(
        "openai", "OpenAI", "gpt-4.5-preview", "https://api.openai.com/v1",
        128_000, "openai", "OpenAI GPT-4.5 Preview", env_name="OPENAI_API_KEY",
    ),
    # OpenRouter suite
    ModelOption(
        "openrouter", "OpenRouter", "anthropic/claude-3.5-sonnet",
        "https://openrouter.ai/api/v1", 200_000, "openrouter",
        "Anthropic Claude 3.5 Sonnet", env_name="OPENROUTER_API_KEY",
    ),
    ModelOption(
        "openrouter", "OpenRouter", "deepseek/deepseek-r1",
        "https://openrouter.ai/api/v1", 128_000, "openrouter",
        "DeepSeek R1 reasoning on OpenRouter", env_name="OPENROUTER_API_KEY",
    ),
    ModelOption(
        "openrouter", "OpenRouter", "google/gemini-2.0-flash-exp:free",
        "https://openrouter.ai/api/v1", 1_000_000, "openrouter",
        "Gemini 2.0 Flash (Free)", env_name="OPENROUTER_API_KEY",
    ),
    ModelOption(
        "openrouter", "OpenRouter", "meta-llama/llama-3.3-70b-instruct",
        "https://openrouter.ai/api/v1", 128_000, "openrouter",
        "Llama 3.3 70B Instruct", env_name="OPENROUTER_API_KEY",
    ),
    ModelOption(
        "openrouter", "OpenRouter", "nvidia/nemotron-3.5-lightning:free",
        "https://openrouter.ai/api/v1", 256_000, "openrouter",
        "Free Nemotron preset", env_name="OPENROUTER_API_KEY",
    ),
    # Groq suite
    ModelOption(
        "groq", "Groq", "llama-3.3-70b-versatile", "https://api.groq.com/openai/v1",
        128_000, "groq", "Fast Groq Llama 3.3", env_name="GROQ_API_KEY",
    ),
    ModelOption(
        "groq", "Groq", "deepseek-r1-distill-llama-70b", "https://api.groq.com/openai/v1",
        128_000, "groq", "Groq DeepSeek R1 Distill", env_name="GROQ_API_KEY",
    ),
    ModelOption(
        "groq", "Groq", "mixtral-8x7b-32768", "https://api.groq.com/openai/v1",
        32_768, "groq", "Fast Groq Mixtral", env_name="GROQ_API_KEY",
    ),
)


def custom_model(
    provider_id: str,
    base_url: str,
    model_id: str,
    context_window: int,
    *,
    credential_id: str | None = None,
    name: str = "",
) -> ModelOption:
    """Build a validated custom OpenAI-compatible option."""
    provider = provider_id.strip().lower()
    url = base_url.strip().rstrip("/")
    model = model_id.strip()
    if not provider or not url.startswith(("http://", "https://")) or not model:
        raise ValueError("Provider, HTTP(S) base URL, and model ID are required.")
    if not 1_024 <= int(context_window) <= 10_000_000:
        raise ValueError("Context window must be between 1,024 and 10,000,000.")
    display_name = name.strip() or provider_id.strip()
    return ModelOption(
        provider, display_name, model, url, int(context_window),
        credential_id or provider, "Custom OpenAI-compatible model",
        env_name=f"{provider.upper().replace('-', '_')}_API_KEY",
    )


def credential_for(option: ModelOption, active_credential_id: str | None = None) -> str:
    """Resolve credentials using provider env first, then OS vault, then HUND_API_KEY if active."""
    return load_api_key(
        option.env_name or "HUND_API_KEY",
        option.credential_id,
        active_credential_id=active_credential_id,
    )


def option_ready(option: ModelOption, active_credential_id: str | None = None) -> bool:
    if not option.is_local:
        return bool(credential_for(option, active_credential_id=active_credential_id))
    try:
        from ..local.engine import LocalEngine

        engine = LocalEngine()
        return engine.model_path is not None and engine.is_running
    except Exception:
        return False


def get_options(cfg: Any, *, include_unconfigured: bool = False) -> list[ModelOption]:
    """Return model options filtered by configured providers, active model, and custom endpoints."""
    from ..secrets import get_credential_status

    options: list[ModelOption] = []
    active_m = getattr(getattr(cfg, "provider", None), "model", "")
    active_u = getattr(getattr(cfg, "provider", None), "base_url", "").rstrip("/")
    active_cred = getattr(getattr(cfg, "provider", None), "credential_id", "")

    configured_cred_ids = set()
    for preset in PROVIDER_PRESETS:
        if preset.provider_id == "custom":
            continue
        cred_state, _ = get_credential_status(preset.credential_id, preset.env_name, active_credential_id=active_cred)
        if cred_state in ("configured", "environment"):
            configured_cred_ids.add(preset.credential_id)

    for opt in MODEL_OPTIONS:
        is_configured = opt.credential_id in configured_cred_ids or option_ready(opt, active_credential_id=active_cred)
        if include_unconfigured or is_configured:
            options.append(opt)

    for ep in getattr(cfg, "custom_endpoints", []):
        try:
            cred_state, _ = get_credential_status(ep.credential_id, "HUND_API_KEY", active_credential_id=active_cred)
            if include_unconfigured or cred_state in ("configured", "environment"):
                opt = custom_model(
                    ep.id, ep.base_url, ep.model_id, ep.context_window,
                    credential_id=ep.credential_id, name=ep.name,
                )
                options.append(opt)
        except Exception:
            pass

    return options


def active_option(cfg: Any) -> ModelOption:
    """Return the configured option even when it is a custom model."""
    active_m = getattr(getattr(cfg, "provider", None), "model", "")
    active_u = getattr(getattr(cfg, "provider", None), "base_url", "").rstrip("/")
    for opt in MODEL_OPTIONS:
        if opt.model_id == active_m and opt.base_url.rstrip("/") == active_u:
            return opt
    for ep in getattr(cfg, "custom_endpoints", []):
        if ep.model_id == active_m and ep.base_url.rstrip("/") == active_u:
            return custom_model(
                ep.id, ep.base_url, ep.model_id, ep.context_window,
                credential_id=ep.credential_id, name=ep.name,
            )
    return custom_model(
        getattr(cfg.provider, "provider_id", "custom"),
        getattr(cfg.provider, "base_url", ""),
        active_m or "unknown",
        getattr(cfg.provider, "context_window", 1_000_000),
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

            key = credential_for(option, active_credential_id=option.credential_id)
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
