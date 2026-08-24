"""Security regression tests for the legacy web_extract alias."""
from pathlib import Path
from unittest.mock import patch

from hund.tools.types import ToolCallContext, ToolKind, ToolStatus, create_success_result
from hund.tools.url_provenance import UrlProvenanceStore
from hund.tools.web_extract import extract_web


def _context() -> ToolCallContext:
    store = UrlProvenanceStore("test")
    store.register_url("https://example.com/", "user_message")
    return ToolCallContext("test", "turn", Path.cwd(), store)


def test_extract_web_requires_tool_context():
    result = extract_web({"url": "https://example.com/"})
    assert result.status == ToolStatus.BLOCKED


def test_extract_web_uses_hardened_web_open_only():
    expected = create_success_result(ToolKind.WEB_PAGE, "safe")
    context = _context()
    with patch("hund.tools.web_extract.open_web", return_value=expected) as open_mock:
        result = extract_web({"url": "https://example.com/"}, context)
    assert result is expected
    open_mock.assert_called_once_with({"url": "https://example.com/"}, context)
