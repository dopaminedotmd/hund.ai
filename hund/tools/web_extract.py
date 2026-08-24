"""Compatibility alias for the hardened :mod:`hund.tools.web_open` path."""
from __future__ import annotations
from typing import Any
from .types import ToolCallContext
from .web_open import open_web

def extract_web(args: dict[str, Any], context: ToolCallContext | None = None):
    """Open a provenance-approved URL through the only network transport."""
    return open_web(args, context)
