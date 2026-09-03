"""agyC/2 — Spår 12: statisk HTML-artefaktkontroll vid write_file."""
from hund.tools.file_tool import make_handlers


def test_html_write_gets_static_note(tmp_path):
    handlers = make_handlers(tmp_path)
    res = handlers["write_file"](
        {"path": "page.html", "content": "<!doctype html><html><body><h1>Hej</h1></body></html>"}
    )
    assert res.status == "created"
    assert "html static check" in res.note
    assert "well-formed" in res.note
    # The note rides on the result string (model-visible) without touching diff
    # counts used by the UI.
    assert "html static check" in str(res)
    assert "html static check" not in (res.display_preview or "")


def test_malformed_html_reports_issue(tmp_path):
    handlers = make_handlers(tmp_path)
    res = handlers["write_file"](
        {"path": "broken.html", "content": "<html><body><div><p>text</div></body>"}
    )
    assert "html static check" in res.note
    assert "well-formed" not in res.note


def test_non_html_write_has_no_note(tmp_path):
    handlers = make_handlers(tmp_path)
    res = handlers["write_file"](
        {"path": "notes.txt", "content": "plain text"}
    )
    assert res.note == ""
