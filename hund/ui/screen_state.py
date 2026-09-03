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
    SYSTEM = "system"
    DOCTOR = "doctor"


class OverlayView(str, Enum):
    NONE = "none"
    CONFIRM = "confirm"
    THEME = "theme"
    MODEL = "model"
    MODEL_CUSTOM = "model_custom"
    MODEL_KEY = "model_key"
    AUTH = "auth"
    AUTH_ADD = "auth_add"
    AUTH_MANAGE = "auth_manage"
    AUTH_KEY = "auth_key"
    AUTH_CUSTOM = "auth_custom"
    AUTH_FORGET_CONFIRM = "auth_forget_confirm"


@dataclass
class ScreenController:
    destination: DestinationView = DestinationView.CHAT
    overlay: OverlayView = OverlayView.NONE
    overlay_source: OverlayView = OverlayView.NONE
    selected: dict[str, int] = field(default_factory=dict)
    scroll: dict[str, int] = field(default_factory=dict)
    detail: dict[str, str | None] = field(default_factory=dict)
    loading: set[str] = field(default_factory=set)
    status: str = ""
    chat_cursor: int = 0
    input_text: str = ""
    # agyD/0 (Gate 3): specialisation two-pane + in-place editor state.
    panel_focus: dict[str, str] = field(default_factory=dict)  # per destination: "left"|"right"
    edit_mode: bool = False
    edit_buffer_text: str = ""

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
        self.overlay_source = self.overlay
        self.overlay = overlay
        self.status = ""
        return True

    def step_back(self) -> str:
        """Step back one level in the hierarchy (e.g. Backspace / Left)."""
        if self.overlay is OverlayView.AUTH_FORGET_CONFIRM:
            self.overlay = OverlayView.AUTH_MANAGE
            return "nested"
        if self.overlay in (OverlayView.AUTH_KEY, OverlayView.AUTH_CUSTOM):
            if self.overlay_source in (OverlayView.AUTH_ADD, OverlayView.AUTH_MANAGE, OverlayView.MODEL):
                self.overlay = self.overlay_source
            else:
                self.overlay = OverlayView.AUTH_ADD
            return "nested"
        if self.overlay in (OverlayView.AUTH_ADD, OverlayView.AUTH_MANAGE):
            if self.overlay_source is OverlayView.MODEL:
                self.overlay = OverlayView.MODEL
            else:
                self.overlay = OverlayView.AUTH
            return "nested"
        if self.overlay in (OverlayView.MODEL_CUSTOM, OverlayView.MODEL_KEY):
            self.overlay = OverlayView.MODEL
            return "nested"
        if self.overlay is not OverlayView.NONE:
            self.overlay = OverlayView.NONE
            return "overlay"
        if self.edit_mode:
            self.edit_mode = False
            return "edit"
        if (
            self.destination is DestinationView.SKILLS
            and self.panel_focus.get(self.destination.value, "left") == "right"
        ):
            self.panel_focus[self.destination.value] = "left"
            return "panel"
        if self.detail.get(self.destination.value):
            self.detail[self.destination.value] = None
            return "detail"
        if self.destination is not DestinationView.CHAT:
            self.destination = DestinationView.CHAT
            self.detail.clear()
            return "destination"
        return "none"

    def close_escape(self) -> str:
        """Close nested modal, modal, or destination in strict priority order."""
        if self.overlay is OverlayView.CONFIRM:
            self.overlay = OverlayView.NONE
            return "confirm"
        if self.overlay in (OverlayView.MODEL_CUSTOM, OverlayView.MODEL_KEY):
            self.overlay = OverlayView.MODEL
            return "nested"
        if self.overlay in (OverlayView.AUTH_KEY, OverlayView.AUTH_CUSTOM):
            if self.overlay_source in (OverlayView.AUTH_ADD, OverlayView.AUTH_MANAGE, OverlayView.MODEL):
                self.overlay = self.overlay_source
            else:
                self.overlay = OverlayView.AUTH_ADD
            return "nested"
        if self.overlay is OverlayView.AUTH_FORGET_CONFIRM:
            self.overlay = OverlayView.AUTH_MANAGE
            return "nested"
        if self.overlay is not OverlayView.NONE:
            self.overlay = OverlayView.NONE
            return "overlay"
        if self.edit_mode:
            self.edit_mode = False
            return "edit"
        if (
            self.destination is DestinationView.SKILLS
            and self.panel_focus.get(self.destination.value, "left") == "right"
        ):
            self.panel_focus[self.destination.value] = "left"
            return "panel"
        if self.detail.get(self.destination.value):
            self.detail[self.destination.value] = None
            return "detail"
        if self.destination is not DestinationView.CHAT:
            self.destination = DestinationView.CHAT
            self.detail.clear()
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
