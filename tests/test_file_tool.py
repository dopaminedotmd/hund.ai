"""Tests for read_file tool offset/limit slicing, error boundaries, CRLF, and notice budgeting."""
from __future__ import annotations

from pathlib import Path
import pytest

from hund.tools.file_tool import make_handlers
from hund.tools.types import ToolKind, create_success_result


def test_read_file_default_reads_up_to_500_lines(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    f = ws / "test.txt"
    content = b"".join(f"line {i}\n".encode("utf-8") for i in range(1, 601))
    f.write_bytes(content)

    handlers = make_handlers(ws)
    res = handlers["read_file"]({"path": "test.txt"})

    assert "line 1\n" in res
    assert "line 500\n" in res
    assert "line 501\n" not in res
    assert "[TRUNCATED — showing lines 1-500 of 600. Use offset=501 to read further.]" in res


def test_read_file_slicing_with_offset_and_limit(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    f = ws / "sample.txt"
    content = b"".join(f"row_{i}\n".encode("utf-8") for i in range(1, 21))
    f.write_bytes(content)

    handlers = make_handlers(ws)
    res = handlers["read_file"]({"path": "sample.txt", "offset": 5, "limit": 3})

    expected = "row_5\nrow_6\nrow_7\n\n\n[TRUNCATED — showing lines 5-7 of 20. Use offset=8 to read further.]"
    assert res == expected


def test_read_file_no_truncation_when_reading_to_end(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    f = ws / "short.txt"
    f.write_bytes(b"line 1\nline 2\nline 3\n")

    handlers = make_handlers(ws)
    res = handlers["read_file"]({"path": "short.txt", "offset": 1, "limit": 10})

    assert res == "line 1\nline 2\nline 3\n"
    assert "[TRUNCATED" not in res


def test_read_file_limit_zero_or_negative_returns_error(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    f = ws / "file.txt"
    f.write_bytes(b"a\nb\nc\n")

    handlers = make_handlers(ws)
    res_zero = handlers["read_file"]({"path": "file.txt", "limit": 0})
    assert res_zero == "[error] limit must be greater than 0, got: 0"

    res_neg = handlers["read_file"]({"path": "file.txt", "limit": -5})
    assert res_neg == "[error] limit must be greater than 0, got: -5"


def test_read_file_offset_less_than_one_coerced_to_one(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    f = ws / "file.txt"
    f.write_bytes(b"first\nsecond\nthird\n")

    handlers = make_handlers(ws)
    res_zero = handlers["read_file"]({"path": "file.txt", "offset": 0, "limit": 2})
    assert res_zero.startswith("first\nsecond\n")

    res_neg = handlers["read_file"]({"path": "file.txt", "offset": -10, "limit": 1})
    assert res_neg.startswith("first\n")


def test_read_file_offset_exceeds_total_lines_returns_error(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    f = ws / "file.txt"
    f.write_bytes(b"one\ntwo\nthree\n")

    handlers = make_handlers(ws)
    res = handlers["read_file"]({"path": "file.txt", "offset": 4})
    assert res == "[error] offset 4 exceeds total lines (3)"


def test_read_file_invalid_integer_args_return_error(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    f = ws / "file.txt"
    f.write_bytes(b"content\n")

    handlers = make_handlers(ws)
    assert handlers["read_file"]({"path": "file.txt", "offset": "bad"}) == "[error] offset must be an integer, got: bad"
    assert handlers["read_file"]({"path": "file.txt", "limit": "bad"}) == "[error] limit must be an integer, got: bad"


def test_read_file_empty_file(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    f = ws / "empty.txt"
    f.write_bytes(b"")

    handlers = make_handlers(ws)
    # Reading empty file from line 1 returns empty string
    res = handlers["read_file"]({"path": "empty.txt", "offset": 1})
    assert res == ""

    # Offset > 1 on empty file returns boundary error
    res_err = handlers["read_file"]({"path": "empty.txt", "offset": 2})
    assert res_err == "[error] offset 2 exceeds total lines (0)"


def test_read_file_crlf_preservation(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    f = ws / "crlf.txt"
    f.write_bytes(b"line 1\r\nline 2\r\nline 3\r\n")

    handlers = make_handlers(ws)
    res = handlers["read_file"]({"path": "crlf.txt", "offset": 2, "limit": 1})

    assert res.startswith("line 2\r\n")
    assert "line 1" not in res
    assert "line 3" not in res


def test_read_file_large_file_over_4000_chars_not_truncated_at_4012(tmp_path: Path):
    """Verify tool output >4000 characters is NOT truncated at 4012 when rendered via ToolResult."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    f = ws / "big.txt"
    # Create 10,000 characters of text
    content = b"abcdefghij\n" * 1000  # 11,000 bytes, 1000 lines
    f.write_bytes(content)

    handlers = make_handlers(ws)
    # Read first 400 lines (~4400 chars)
    raw_res = handlers["read_file"]({"path": "big.txt", "offset": 1, "limit": 400})
    assert len(raw_res) > 4000

    # Wrap in ToolResult and call to_llm_text()
    result = create_success_result(ToolKind.FILE, raw_res)
    llm_text = result.to_llm_text()

    assert len(llm_text) > 4000
    assert "[TRUNCATED — showing lines 1-400 of 1000" in llm_text
    # Ensure it wasn't cut off at 4000 + 12 = 4012 by old redactor default
    assert "abcdefghij\n" in llm_text[4000:]


def test_read_file_notice_budget_survives_redaction_near_50k(tmp_path: Path):
    """Verify content + notice capped at 49,500 chars survives redact_text(max_chars=50_000)."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    f = ws / "massive.txt"
    # Create 80,000 characters across 100 lines (each line 800 chars)
    line = b"x" * 799 + b"\n"
    f.write_bytes(line * 100)

    handlers = make_handlers(ws)
    raw_res = handlers["read_file"]({"path": "massive.txt", "offset": 1, "limit": 80})

    # The raw_res has capped content (49,500) + notice (~100 chars) = ~49,600 chars
    assert "[TRUNCATED — showing lines 1-80 of 100." in raw_res
    assert len(raw_res) <= 50_000

    # Pass through to_llm_text()
    result = create_success_result(ToolKind.FILE, raw_res)
    llm_text = result.to_llm_text()

    # The [TRUNCATED] notice MUST survive and NOT be stripped away by redact_text
    assert "[TRUNCATED — showing lines 1-80 of 100. Use offset=81 to read further.]" in llm_text
    assert "[TRUNCATED: max chars exceeded]" not in llm_text
