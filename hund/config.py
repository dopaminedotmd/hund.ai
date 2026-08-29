"""Konfiguration — validerad med pydantic.

SECURITY: API-nyckel lagras ALDRIG i config.json i klartext.
Mål: Windows DPAPI / Credential Manager (se docs/architecture.md §TCB).
I 0.1.0 sparas nyckel i miljövariabel eller OS-nyckelring — TODO innan setup.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil

from pydantic import BaseModel, Field, PrivateAttr

from .paths import config_path


# Valid DeepSeek model names (single source of truth).
# flash = billigare. pro = högre precision.
KNOWN_MODELS = (
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-v4-flash-vision-exp",
    "deepseek-chat",
    "deepseek-reasoner",
)


class CustomEndpoint(BaseModel):
    """User-defined OpenAI-compatible endpoint."""

    id: str
    name: str
    base_url: str
    model_id: str
    context_window: int = 32_000
    credential_id: str


class ProviderConfig(BaseModel):
    """OpenAI-compatible provider i v1 (en shape, BYOK). Default: DeepSeek."""

    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    # api_key hanteras separat — ALDRIG serialiserad till disk.
    api_key_env: str = "DEEPSEEK_API_KEY"
    provider_id: str = "deepseek"
    credential_id: str = "deepseek"
    context_window: int = 1_000_000


class HundConfig(BaseModel):
    """Hund runtime-konfiguration."""

    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    custom_endpoints: list[CustomEndpoint] = Field(default_factory=list)
    workspace_root: Path | None = None  # None = cwd. Workspace-confined.
    telemetry_local: bool = True  # lokal prestandalog: på som default
    telemetry_upload: bool = False  # extern upload: AV som default (inte i v1)
    theme: str = "marshmallow"  # Hund's signature theme and current sole skin.
    reduced_motion: bool = False
    screen_reader: bool = False
    ascii_ui: bool = False
    enable_on_demand_publication: bool = True
    enable_skill_observation: bool = True
    enable_skill_proposals: bool = True
    enable_skill_materialization: bool = True

    _recovery_notice: str | None = PrivateAttr(default=None)

    @classmethod
    def load(cls, path: Path | None = None) -> "HundConfig":
        path = path or config_path()
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                cfg = cls.model_validate_json(content)
                # Sanitize DeepSeek model name if invalid or legacy
                if "deepseek.com" in cfg.provider.base_url and (
                    cfg.provider.model.startswith("gpt-") or cfg.provider.model not in KNOWN_MODELS
                ):
                    cfg.provider.model = "deepseek-v4-flash"
                if cfg.provider.context_window == 64_000:
                    cfg.provider.context_window = 1_000_000
                # Marshmallow is Hund's sole current theme. Migrate every
                # historical or unknown persisted value deterministically.
                if cfg.theme != "marshmallow":
                    cfg.theme = "marshmallow"
                return cfg
            except Exception:
                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                backup_path = path.with_name(f"{path.name}.corrupt.{ts}")
                try:
                    shutil.copy2(path, backup_path)
                except Exception:
                    pass
                fallback = cls()
                fallback._recovery_notice = f"Recovered corrupted config. Backup saved to {backup_path.name}"
                return fallback
        return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
