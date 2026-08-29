"""Unicode grapheme cluster slicing, safe cell width measurement, and wrapping."""
from __future__ import annotations

import re
from typing import Iterator
import wcwidth

# Extended grapheme cluster regex matching base character + combining marks,
# variation selectors, skin tone modifiers, and zero-width-joiner (ZWJ) sequences.
_GRAPHEME_CLUSTER_RE = re.compile(
    r"(?:\r\n|[\s\S])"
    r"(?:[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f\ufe00-\ufe0f\U0001F3FB-\U0001F3FF]"
    r"|(?:\u200d[\s\S]))*"
)

# Comprehensive ANSI escape sequence regexes
_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_OTHER_ESC_RE = re.compile(r"\x1b[PX^_][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")


def strip_ansi_sequences(text: str) -> str:
    """Strip complete CSI, OSC, and 2-byte escape sequences from text."""
    if not text or "\x1b" not in text:
        return text
    cleaned = _CSI_RE.sub("", text)
    cleaned = _OSC_RE.sub("", cleaned)
    cleaned = _OTHER_ESC_RE.sub("", cleaned)
    return cleaned


class AnsiStreamSanitizer:
    """Stateful stream sanitizer handling incomplete ANSI/CSI/OSC sequences across chunks."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, text: str) -> str:
        if not text:
            return ""
        self._buf += text
        if "\x1b" not in self._buf:
            out = self._buf
            self._buf = ""
            return out

        out_parts: list[str] = []
        i = 0
        n = len(self._buf)

        while i < n:
            esc_pos = self._buf.find("\x1b", i)
            if esc_pos == -1:
                out_parts.append(self._buf[i:])
                i = n
                break

            # Append text before ESC
            if esc_pos > i:
                out_parts.append(self._buf[i:esc_pos])
                i = esc_pos

            # Look ahead for sequence completion
            rem = n - i
            if rem == 1:
                # Trailing bare ESC - wait for next chunk
                break

            second_char = self._buf[i + 1]
            if second_char == "[":
                # CSI sequence: \x1b\[[0-9;?]*[ -/]*[@-~]
                m = _CSI_RE.match(self._buf, i)
                if m:
                    i = m.end()
                    continue
                else:
                    # Incomplete CSI sequence - wait for terminating byte
                    break
            elif second_char == "]":
                # OSC sequence: \x1b\][^\x07\x1b]*(?:\x07|\x1b\\)
                m = _OSC_RE.match(self._buf, i)
                if m:
                    i = m.end()
                    continue
                else:
                    # Incomplete OSC sequence - wait for BEL or ST
                    break
            elif second_char in "PX^_":
                # DCS, SOS, PM, APC sequences terminated by ST or BEL
                m = _OTHER_ESC_RE.match(self._buf, i)
                if m:
                    i = m.end()
                    continue
                else:
                    break
            else:
                # Simple 2-byte escape
                i += 2
                continue

        self._buf = self._buf[i:]
        return "".join(out_parts)

    def flush(self) -> str:
        # At EOF, if buffer still has an incomplete sequence, discard the ESC sequence safely
        buf = self._buf
        self._buf = ""
        if "\x1b" in buf:
            return strip_ansi_sequences(re.sub(r"\x1b.*$", "", buf))
        return buf


def iter_grapheme_clusters(text: str) -> Iterator[str]:
    """Yield user-perceived grapheme clusters without breaking combining marks or ZWJ sequences."""
    if not text:
        return
    for match in _GRAPHEME_CLUSTER_RE.finditer(text):
        yield match.group(0)


def sanitize_ansi_snapshot(text: str) -> str:
    """Sanitize ANSI/CSI/OSC sequences from a string snapshot, safely hiding incomplete sequences."""
    if not text or "\x1b" not in text:
        return text
    sanitizer = AnsiStreamSanitizer()
    return sanitizer.feed(text) + sanitizer.flush()


def sanitize_display_line(text: str) -> str:
    """Strip ANSI sequences (including incomplete sequences), expand tabs, and strip control chars for display."""
    if not text:
        return ""
    # Strip ANSI escape sequences safely hiding incomplete control sequences
    text = sanitize_ansi_snapshot(text)
    # Expand tabs deterministically
    text = text.replace("\t", "    ")
    # Filter out ASCII control characters except newline/carriage return
    cleaned = "".join(
        ch for ch in text
        if (ord(ch) >= 32 or ch in "\n\r") and ord(ch) != 127
    )
    return cleaned


def cell_width(text: str) -> int:
    """Return the visible terminal cell width of text using wcwidth.

    Returns 0 for empty strings, handles multi-byte CJK (width 2), emojis,
    and safely falls back for unmeasured control characters without returning -1.
    """
    if not text:
        return 0
    w = wcwidth.wcswidth(text)
    if w >= 0:
        return w

    # If wcswidth returns -1 due to unprintable/control characters, evaluate clusters safely
    total = 0
    for cluster in iter_grapheme_clusters(text):
        if not cluster:
            continue
        cw = wcwidth.wcwidth(cluster[0])
        if cw < 0:
            cw = 0 if cluster in ("\r", "\n", "\t", "\x00", "\x1b") else 1
        total += cw
    return total


def slice_cells(text: str, max_cells: int) -> tuple[str, int]:
    """Slice text up to max_cells without breaking grapheme clusters.

    Returns (sliced_text, actual_cell_width).
    """
    if max_cells <= 0 or not text:
        return "", 0

    accum_clusters: list[str] = []
    current_cells = 0
    for cluster in iter_grapheme_clusters(text):
        cw = cell_width(cluster)
        if current_cells + cw > max_cells:
            break
        accum_clusters.append(cluster)
        current_cells += cw
    return "".join(accum_clusters), current_cells


def wrap_cells(text: str, max_cells: int) -> list[str]:
    """Deterministically wrap text to fit within max_cells visible columns.

    - Preserves empty lines as semantic content.
    - Expands tabs to 4 spaces.
    - Wraps at whitespace boundaries when possible.
    - Hard-breaks long unbreakable tokens/words without splitting grapheme clusters.
    """
    if not text:
        return []

    cw = max(int(max_cells), 1)
    wrapped: list[str] = []

    for raw_line in text.split("\n"):
        line = sanitize_display_line(raw_line)
        if not line:
            wrapped.append("")
            continue

        # If line already fits, keep it
        if cell_width(line) <= cw:
            wrapped.append(line)
            continue

        # Word-wrap using cluster-aware measurement
        words = line.split(" ")
        current_line_parts: list[str] = []
        current_line_width = 0

        for word in words:
            word_w = cell_width(word)
            space_w = 1 if current_line_parts else 0

            if current_line_width + space_w + word_w <= cw:
                if current_line_parts:
                    current_line_parts.append(" ")
                    current_line_width += 1
                current_line_parts.append(word)
                current_line_width += word_w
            else:
                # Flush current line if not empty
                if current_line_parts:
                    wrapped.append("".join(current_line_parts))
                    current_line_parts = []
                    current_line_width = 0

                # If word itself is longer than cw, hard-slice it
                if word_w > cw:
                    rem_word = word
                    while cell_width(rem_word) > cw:
                        chunk, chunk_w = slice_cells(rem_word, cw)
                        if not chunk:
                            # Safeguard against zero slice
                            chunk = next(iter_grapheme_clusters(rem_word), rem_word[:1])
                            chunk_w = cell_width(chunk)
                        wrapped.append(chunk)
                        rem_word = rem_word[len(chunk):]
                    if rem_word:
                        current_line_parts.append(rem_word)
                        current_line_width = cell_width(rem_word)
                else:
                    current_line_parts.append(word)
                    current_line_width = word_w

        if current_line_parts:
            wrapped.append("".join(current_line_parts))

    return wrapped
