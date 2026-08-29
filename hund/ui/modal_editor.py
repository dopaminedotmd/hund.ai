"""Unified modal text editing, masking, word deletion, and paste handling."""
from __future__ import annotations


class ModalTextEditor:
    """Manages text input in modal dialogs (secrets, URLs, custom endpoints)."""

    def __init__(self, initial_text: str = "") -> None:
        self.text: str = initial_text

    def __repr__(self) -> str:
        return f"ModalTextEditor(chars={len(self.text)}, masked='{self.get_masked()}')"

    def __str__(self) -> str:
        return self.get_masked()

    def set_text(self, text: str) -> None:
        self.text = text

    def insert_text(self, new_text: str) -> None:
        """Insert text, sanitizing newlines and control chars."""
        if not new_text:
            return
        cleaned = (
            new_text.replace("\r\n", "")
            .replace("\r", "")
            .replace("\n", "")
            .replace("\t", " ")
        )
        # Filter out non-printable ASCII/Unicode control characters except space
        cleaned = "".join(c for c in cleaned if c.isprintable() or c == " ")
        self.text += cleaned

    def delete_char(self) -> None:
        """Delete one character from the end."""
        if self.text:
            self.text = self.text[:-1]

    def delete_word(self) -> None:
        """Delete the previous word/token from the end."""
        self.text = self.calc_deleted_word(self.text)

    def clear(self) -> None:
        """Clear all text."""
        self.text = ""

    def get_masked(self) -> str:
        """Return masked representation (e.g. for secret API keys)."""
        return "•" * len(self.text)

    def get_raw(self) -> str:
        """Return the raw underlying text."""
        return self.text

    @staticmethod
    def calc_deleted_word(text: str) -> str:
        """Delete previous token with respect to hyphens, URLs, paths, and spaces."""
        if not text:
            return ""
        i = len(text)
        # 1. Skip trailing whitespace
        while i > 0 and text[i - 1].isspace():
            i -= 1
        if i == 0:
            return ""
        # 2. If char is alphanumeric or underscore
        if text[i - 1].isalnum() or text[i - 1] == "_":
            while i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_"):
                i -= 1
        else:
            # Punctuation / symbol chunk (e.g. "://", "/", "-", ".", etc.)
            while i > 0 and not text[i - 1].isalnum() and not text[i - 1].isspace() and text[i - 1] != "_":
                i -= 1
        return text[:i]
