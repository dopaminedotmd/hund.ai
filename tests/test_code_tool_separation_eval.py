"""Evaluation fixtures testing code vs tool-turn separation."""
import pytest
from hund.ui.activity import ActivityTimeline, ActivityStatus
from hund.ui.output import SegmentType, parse_semantic_segments


def test_strong_provider_code_response_separation():
    # Strong provider: structured prose + clear fenced code
    response_text = (
        "hund recommends using standard pathlib for this task.\n\n"
        "```python\n"
        "from pathlib import Path\n\n"
        "def read_text(path: str) -> str:\n"
        "    return Path(path).read_text(encoding='utf-8')\n"
        "```"
    )
    segs = parse_semantic_segments(response_text)
    assert len(segs) == 2
    assert segs[0].type == SegmentType.PROSE
    assert segs[1].type == SegmentType.CODE
    assert segs[1].language == "python"


def test_executed_tool_activity_separated_from_chat_response():
    timeline = ActivityTimeline()
    eid = timeline.start("edit_file", "modified config.py", group="edit")
    timeline.finish(eid, ActivityStatus.COMPLETE, duration_s=0.2)

    # The assistant response should contain advice, not raw executed tool diffs
    assistant_response = "Updated the configuration file successfully."
    segs = parse_semantic_segments(assistant_response)

    activity_lines = timeline.render_lines()
    assert any("modified config.py" in l for l in activity_lines)
    assert len(segs) == 1
    assert segs[0].type == SegmentType.PROSE
    assert "modified config.py" not in segs[0].lines[0]
