"""Slash-autocomplete — NestedCompleter-träd wrappat i FuzzyCompleter.

`build_completer()` returnerar ett NestedCompleter; anroparen wrapar det i
`FuzzyCompleter(build_completer())`. Med `complete_while_typing=True` på
PromptSession visas dropdown automatiskt när användaren trycker `/`.
"""
from __future__ import annotations

from prompt_toolkit.completion import NestedCompleter


def build_completer() -> NestedCompleter:
    """Returnera NestedCompleter med slash-kommandon + /sessions-subkommandon.

    Leaf `None` = token komplett, inga djupare completions (fri text för arg).
    """
    return NestedCompleter.from_nested_dict(
        {
            "/sessions": {"list": None, "search": None, "resume": None, "new": None},
            "/stats": None,
            "/profile": None,
            "/tools": None,
            "/exit": None,
            "/quit": None,
            "/help": None,
        }
    )
