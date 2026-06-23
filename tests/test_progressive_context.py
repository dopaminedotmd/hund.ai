"""Tester för progressive context discovery."""
from pathlib import Path
from hund.agent.progressive_context import SubdirectoryHintTracker


def test_discover_finds_context_file(tmp_path):
    """Sök efter kontextfiler uppåt i filträdet."""
    # Skapa a/b/c
    dir_c = tmp_path / "a" / "b" / "c"
    dir_c.mkdir(parents=True)
    
    # Skapa CLAUDE.md i /a/
    claude_file = tmp_path / "a" / "CLAUDE.md"
    claude_file.write_text("Detta är Claude kontext", encoding="utf-8")
    
    tracker = SubdirectoryHintTracker()
    
    # discover från /a/b/c ska gå upp till /a/ och hitta CLAUDE.md
    res = tracker.discover(dir_c, tmp_path)
    
    assert res is not None
    assert "[context from a/CLAUDE.md]" in res
    assert "Detta är Claude kontext" in res


def test_discover_ignores_checked(tmp_path):
    """Om en katalog redan har sökts igenom ska den inte ge träff igen (vi sparar i checked)."""
    dir_b = tmp_path / "a" / "b"
    dir_b.mkdir(parents=True)
    
    claude_file = tmp_path / "a" / "CLAUDE.md"
    claude_file.write_text("Kontext text", encoding="utf-8")
    
    tracker = SubdirectoryHintTracker()
    
    # Första sökningen hittar filen
    res1 = tracker.discover(dir_b, tmp_path)
    assert res1 is not None
    
    # Andra sökningen från samma katalog (eller underkatalog som går förbi a) ska returnera None
    # eftersom /a/b och /a/ redan har lagts till i _checked
    res2 = tracker.discover(dir_b, tmp_path)
    assert res2 is None
