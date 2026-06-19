"""Hund-maskot — pixel art för terminalen.

Renderar hunden som Rich-formaterad text med rätt färger.
Design: Williams Minecraft-inspirerade hundhuvud.
"""

from rich.text import Text

# Rå grid — Williams design
#   ░ = ansikte (offwhite)
#   █ = ögon/mun (svart)
#   mellanslag = genomskinligt
GRID = [
    "        ░░    ░░░░  ",
    "        ░░░░░░░░    ",
    "        ░░██░░██░░  ",
    "        ░░░░░░░░░░██",
    "░░    ░░░░░░░░░░░░  ",
    "░░  ░░░░░░░░░░░░    ",
    "░░  ░░░░░░░░░░░░    ",
    "░░░░░░░░░░░░░░░░    ",
    "  ░░░░░░  ░░  ░░    ",
]

# Rich-färger
COLORS = {
    "█": "#000000",  # Svart — ögon, mun
    "░": "#F5F0E8",  # Offwhite — ansikte
}

# Animation frames (framtida — använder frame 0 tills vidare)
FRAMES = {
    "idle": [0],
    "blink": [0, 1],
    "happy": [2],
    "thinking": [3],
}


def render() -> Text:
    """Returnera hunden som Rich Text (statisk, idle)."""
    return _render_frame(GRID)


def render_state(state: str = "idle") -> Text:
    """Returnera hunden för given state.

    States: idle, blink, happy, thinking
    """
    # Alla states använder samma grid tills animationer implementeras
    return _render_frame(GRID)


def _render_frame(grid: list[str]) -> Text:
    """Bygg Rich Text från grid."""
    text = Text()
    for row in grid:
        for ch in row:
            if ch in COLORS:
                text.append(ch, style=COLORS[ch])
            else:
                text.append(" ")
        text.append("\n")
    return text


# ASCII-version (inga Rich-taggar) — för loggar, plain-text output
ASCII_ART = """\
        ░░    ░░░░  
        ░░░░░░░░    
        ░░██░░██░░  
        ░░░░░░░░░░██
░░    ░░░░░░░░░░░░  
░░  ░░░░░░░░░░░░    
░░  ░░░░░░░░░░░░    
░░░░░░░░░░░░░░░░    
  ░░░░░░  ░░  ░░    """
