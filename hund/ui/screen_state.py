"""Central navigation state for fullscreen destinations and modal overlays."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DestinationView(str, Enum):
    CHAT = "chat"
    STATS = "stats"
    SKILLS = "skills"
    TOOLS = "tools"
    USAGE = "usage"


class OverlayView(str, Enum):
    NONE = "none"
    CONFIRM = "confirm"
    THEME = "theme"
    MODEL = "model"
    MODEL_CUSTOM = "model_custom"
    MODEL_KEY = "model_key"


@dataclass
class ScreenController:
    destination: DestinationView = DestinationView.CHAT
    overlay: OverlayView = OverlayView.NONE
    selected: dict[str, int] = field(default_factory=dict)
    scroll: dict[str, int] = field(default_factory=dict)
    detail: dict[str, str | None] = field(default_factory=dict)
    loading: set[str] = field(default_factory=set)
    status: str = ""
    chat_cursor: int = 0
    input_text: str = ""

    def open_destination(self, destination: DestinationView) -> bool:
        if self.overlay is OverlayView.CONFIRM:
            return False
        self.destination = destination
        self.overlay = OverlayView.NONE
        self.status = ""
        return True

    def open_overlay(self, overlay: OverlayView) -> bool:
        if self.overlay is OverlayView.CONFIRM and overlay is not OverlayView.CONFIRM:
            return False
        self.overlay = overlay
        self.status = ""
        return True

    def close_escape(self) -> str:
        """Close nested modal, modal, or destination in strict priority order."""
        if self.overlay is OverlayView.CONFIRM:
            self.overlay = OverlayView.NONE
            return "confirm"
        if self.overlay in (OverlayView.MODEL_CUSTOM, OverlayView.MODEL_KEY):
            self.overlay = OverlayView.MODEL
            return "nested"
        if self.overlay is not OverlayView.NONE:
            self.overlay = OverlayView.NONE
            return "overlay"
        if self.detail.get(self.destination.value):
            self.detail[self.destination.value] = None
            return "detail"
        if self.destination is not DestinationView.CHAT:
            self.destination = DestinationView.CHAT
            return "destination"
        return "chat"

    def move(self, key: str, delta: int, count: int) -> int:
        if count <= 0:
            self.selected[key] = 0
        else:
            self.selected[key] = (self.selected.get(key, 0) + delta) % count
        return self.selected[key]

    def scroll_by(self, key: str, delta: int, maximum: int) -> int:
        self.scroll[key] = max(0, min(maximum, self.scroll.get(key, 0) + delta))
        return self.scroll[key]
