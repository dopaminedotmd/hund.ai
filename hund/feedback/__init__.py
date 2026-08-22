"""Behavior Feedback Loop — Hunds självförbättrande intelligens.

Efter varje agent-turn extraheras lärdomar från trace DB, komprimeras till
kortfattade regler, lagras i SQLite och injiceras i systemprompten nästa
session. Agenten blir bättre för varje körning — utan fler funktioner.
"""

from __future__ import annotations

from .extract import extract_lessons
from .compress import compress_lessons
from .store import FeedbackStore

__all__ = ["extract_lessons", "compress_lessons", "FeedbackStore"]
