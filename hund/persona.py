"""Hunds persona — laddar riktig röst om tillgänglig, annars skeleton.

Sökningsordning:
  1. HUND_PERSONA_PATH (env, explicit override)
  2. HundHome/brain/persona.md  (kanonisk, redigerbar — fas 9.5 Del C)
  3. ./hund-system/hund.md  (sibling checkout)
  4. ~/Desktop/hund-system/hund.md  (Williams dev-plats)
  5. bundled assets/hund-system/hund.md  (framtida, vid paketering)
  6. DEFAULT_PERSONA (skeleton)
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PERSONA = """\
Du är hund — en symbiotisk AI-assistent som lever i användarens maskin.
hund talar alltid i tredje person ("hund tycker", "hund föreslår").
hund använder aldrig emojis. Rösten är varm men precis, kortfattad men exakt.
hund är en levande närvaro i systemet, inte en generisk assistent.

(placeholder-persona — full röst laddas från HundHome/brain/persona.md)
"""

_PERSONA_CANDIDATES = [
    Path("hund-system") / "hund.md",
    Path.home() / "Desktop" / "hund-system" / "hund.md",
    Path(__file__).parent / "assets" / "hund-system" / "hund.md",
]


def load_persona() -> str:
    from .paths import brain_persona_path

    env_path = os.environ.get("HUND_PERSONA_PATH")
    if env_path:
        try:
            override = Path(env_path)
            if override.is_file():
                return override.read_text(encoding="utf-8-sig")
        except OSError:
            pass

    canonical = brain_persona_path()
    try:
        if canonical.is_file():
            return canonical.read_text(encoding="utf-8-sig")
    except OSError:
        pass

    for c in _PERSONA_CANDIDATES:
        try:
            if c.is_file():
                text = c.read_text(encoding="utf-8-sig")
                # First-run seed: make the actually loaded full persona canonical
                # and editable without ever overwriting an existing user version.
                try:
                    canonical.parent.mkdir(parents=True, exist_ok=True)
                    with canonical.open("x", encoding="utf-8", newline="\n") as fh:
                        fh.write(text)
                except (FileExistsError, OSError):
                    pass
                return text
        except OSError:
            continue
    return DEFAULT_PERSONA
