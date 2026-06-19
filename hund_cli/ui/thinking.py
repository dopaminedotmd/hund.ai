"""Animerad tänketext — prickcykel som visas medan agenten jobbar.

SÄKER bara för att den kör under `_agent_turn` (efter att `session.prompt()`
returnerat, dvs. ingen aktiv prompt_toolkit-prompt äger terminalen). Tråden
skriver rå ANSI till sys.stdout; stop() suddar raden så det buffrade svaret
skrivs rent.

Fall-back: om stdout inte är en TTY (rör/CI) eller HUND_NO_ANIMATE=1 satt,
skrivs en statisk rad utan cykel — undviker kvarlämnade prickar där
\\033[K (clear-line) inte stöds.
"""
from __future__ import annotations

import os
import sys
import threading

# CR + clear-to-end-of-line: flytta cursor till kolumn 0, sudda resten av raden.
_CLEAR_LINE = "\r\033[K"


class ThinkingAnimator:
    """Cyklar 'hund undersöker' → '..' → '...' med `interval` sekunder."""

    def __init__(self, interval: float = 0.4) -> None:
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._text = "hund tänker"

    @staticmethod
    def _animated() -> bool:
        if os.environ.get("HUND_NO_ANIMATE"):
            return False
        try:
            return bool(sys.stdout.isatty())
        except Exception:
            return False

    def start(self, text: str | None = None) -> None:
        if self._thread and self._thread.is_alive():
            return  # redan igång
        if text:
            self._text = text
        self._stop.clear()
        if not self._animated():
            sys.stdout.write(_CLEAR_LINE + self._text)
            sys.stdout.flush()
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        dots = 0
        while not self._stop.is_set():
            frame = f"{self._text}{'.' * (dots % 3 + 1)}"
            sys.stdout.write(_CLEAR_LINE + frame)
            sys.stdout.flush()
            dots += 1
            self._stop.wait(self._interval)

    def stop(self) -> None:
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=1.0)
            self._thread = None
        # Sudda raden så nästa utskrift (det buffrade svaret) hamnar rent.
        sys.stdout.write(_CLEAR_LINE)
        sys.stdout.flush()
