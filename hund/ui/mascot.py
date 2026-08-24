"""Mascot animation state machine backed by pre-rendered frames."""
from __future__ import annotations

from enum import Enum
import time

from .mascot_frames import FRAMES, TINTS


class MascotState(str, Enum):
    SITTING = "sitting"
    RUNNING = "running"
    PLAYFUL = "playful"
    STANDING = "standing"


class MascotMachine:
    """Small deterministic state machine; new work always overrides playful."""

    PLAYFUL_HOLD_SECONDS = 6.0
    STANDING_HOLD_SECONDS = 45.0

    _FRAME_SECONDS = {
        MascotState.SITTING: 0.35,
        MascotState.RUNNING: 0.12,
        MascotState.PLAYFUL: 0.14,
        MascotState.STANDING: 0.28,
    }
    # Terminal half-blocks erase most of the subtle source-pixel motion.
    # These source-order keyframes guarantee a visible silhouette change.
    _FRAME_ORDER = {
        MascotState.SITTING: (0, 6),
        MascotState.RUNNING: (0, 1, 2, 3),
        MascotState.PLAYFUL: (0, 1, 6, 7, 8, 9, 12, 14, 15),
        MascotState.STANDING: (0, 4, 5, 6),
    }

    def __init__(self) -> None:
        self.state = MascotState.SITTING
        self.entered_at = time.monotonic()

    def _set(self, state: MascotState, now: float | None = None) -> None:
        self.state = state
        self.entered_at = time.monotonic() if now is None else now

    def start_turn(self) -> None:
        self._set(MascotState.RUNNING)

    def finish_turn(self) -> None:
        self._set(MascotState.PLAYFUL)

    def frame(self, skin: str = "marshmallow", now: float | None = None) -> tuple[str, str]:
        current = time.monotonic() if now is None else now
        elapsed = current - self.entered_at
        if self.state is MascotState.PLAYFUL and elapsed >= self.PLAYFUL_HOLD_SECONDS:
            self._set(MascotState.STANDING, current)
            elapsed = 0.0
        elif self.state is MascotState.STANDING and elapsed >= self.STANDING_HOLD_SECONDS:
            self._set(MascotState.SITTING, current)
            elapsed = 0.0

        asset_skin = "bone" if skin in {"bone", "marshmallow"} else skin
        clips = FRAMES.get(asset_skin, FRAMES["bone"])[self.state.value]
        frame_seconds = self._FRAME_SECONDS[self.state]
        order = self._FRAME_ORDER[self.state]
        order_index = int((elapsed + 1e-9) / frame_seconds) % len(order)
        return TINTS.get(asset_skin, TINTS["bone"]), clips[order[order_index]]
