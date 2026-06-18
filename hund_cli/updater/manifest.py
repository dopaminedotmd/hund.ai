"""Release manifest — datamodell för pinnadt release.

Ett release-manifest knyter en specifik version till ett commit SHA och
ett SHA256-checksumma för installationsskriptet. Installeraren pinnar detta
manifest och verifierar checksumman innan exekvering.

Format (JSON):
    {
        "version": "0.1.0",
        "commit_sha": "37947cb...",
        "install_ps1_sha256": "abc123...",
        "install_sh_sha256":  "def456...",
        "released_at": "2026-06-18T00:00:00Z",
        "channel": "stable"
    }

TCB: Manifest-valideringen räknas som TCB-kod. Hund får aldrig föreslå
ändringar i detta paket som auto-applicerbara.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

MANIFEST_SCHEMA_VERSION = 1

# Kanaler: "stable" får ej peka på en gren-HEAD utan måste ha commit_sha.
VALID_CHANNELS = {"stable", "dev"}


@dataclass
class ReleaseManifest:
    version: str
    commit_sha: str
    install_ps1_sha256: str
    install_sh_sha256: str
    released_at: str
    channel: str = "stable"
    schema_version: int = MANIFEST_SCHEMA_VERSION

    # ------------------------------------------------------------------ #
    # Serialisering                                                        #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, d: dict) -> "ReleaseManifest":
        return cls(
            version=d["version"],
            commit_sha=d["commit_sha"],
            install_ps1_sha256=d["install_ps1_sha256"],
            install_sh_sha256=d["install_sh_sha256"],
            released_at=d["released_at"],
            channel=d.get("channel", "stable"),
            schema_version=d.get("schema_version", MANIFEST_SCHEMA_VERSION),
        )

    @classmethod
    def from_json(cls, text: str) -> "ReleaseManifest":
        return cls.from_dict(json.loads(text))

    @classmethod
    def from_file(cls, path: Path) -> "ReleaseManifest":
        return cls.from_json(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ #
    # Validering                                                           #
    # ------------------------------------------------------------------ #

    def validate(self) -> list[str]:
        """Returnerar lista med fel (tom = OK)."""
        errors: list[str] = []
        if not self.version:
            errors.append("version saknas")
        if not self.commit_sha or len(self.commit_sha) < 7:
            errors.append("commit_sha saknas eller för kort (min 7 tecken)")
        if self.channel == "stable":
            if not self.install_ps1_sha256 or len(self.install_ps1_sha256) != 64:
                errors.append("install_ps1_sha256 måste vara 64-teckens hex (SHA256)")
            if not self.install_sh_sha256 or len(self.install_sh_sha256) != 64:
                errors.append("install_sh_sha256 måste vara 64-teckens hex (SHA256)")
        if self.channel not in VALID_CHANNELS:
            errors.append(f"okänd kanal: {self.channel!r} (tillåtna: {VALID_CHANNELS})")
        return errors

    def is_valid(self) -> bool:
        return not self.validate()
