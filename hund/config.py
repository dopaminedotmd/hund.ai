"""Konfiguration — validerad med pydantic.

SECURITY: API-nyckel lagras ALDRIG i config.json i klartext.
Mål: Windows DPAPI / Credential Manager (se docs/architecture.md §TCB).
I 0.1.0 sparas nyckel i miljövariabel eller OS-nyckelring — TODO innan setup.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from .paths import config_path


class ProviderConfig(BaseModel):
    """OpenAI-compatible provider i v1 (en shape, BYOK). Default: Z.AI (GLM)."""

    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-pro"  # deepseek-v4-flash = billigare
    # api_key hanteras separat — ALDRIG serialiserad till disk.
    api_key_env: str = "HUND_API_KEY"


class HundConfig(BaseModel):
    """Hund runtime-konfiguration."""

    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    workspace_root: Path | None = None  # None = cwd. Workspace-confined.
    telemetry_local: bool = True  # lokal prestandalog: på som default
    telemetry_upload: bool = False  # extern upload: AV som default (inte i v1)

    @classmethod
    def load(cls, path: Path | None = None) -> "HundConfig":
        path = path or config_path()
        if path.exists():
            return cls.model_validate_json(path.read_text(encoding="utf-8"))
        return cls()  # default

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
