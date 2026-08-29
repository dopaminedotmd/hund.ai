"""Tests for Gate A1: Fail-closed DSML and provider protocol sanitization."""
import pytest

from hund.providers.openai_compatible import (
    filter_leaked_protocol,
    StreamProtocolFilter,
)
from hund.agent.narrative_validation import (
    validate_narrative_text,
    repair_narrative_prose,
    validate_and_repair_response,
)


class TestDSMLProtocolFiltering:
    def test_complete_dsml_block_filtered(self):
        raw = 'Text before <DSMLtool_calls><DSMLinvoke name="read_file">{"path":"a.py"}</DSMLinvoke></DSMLtool_calls> text after.'
        cleaned = filter_leaked_protocol(raw)
        assert "<DSML" not in cleaned
        assert "read_file" not in cleaned
        assert "Text before" in cleaned
        assert "text after." in cleaned

    def test_dsml_tool_call_singular_and_variations(self):
        raw = 'Hello <DSMLtool_call><DSMLinvoke name="execute">args</DSMLinvoke></DSMLtool_call> world.'
        cleaned = filter_leaked_protocol(raw)
        assert "<DSML" not in cleaned
        assert "Hello" in cleaned
        assert "world." in cleaned

    def test_dangling_dsml_markers_filtered(self):
        cases = [
            "Start <DSMLtool_calls> middle </DSMLtool_calls> end",
            "Start <DSMLinvoke name=\"run\"> middle </DSMLinvoke> end",
            "Start <dsmltool_calls> middle </dsmltool_calls> end",
            "Start <DSMLtool_call> middle </DSMLtool_call> end",
            "Start <DSML> middle </DSML> end",
            "Dangling opening <DSMLtool_calls> only",
            "Dangling closing </DSMLtool_calls> only",
            "Dangling invoke <DSMLinvoke name=\"cmd\" /> only",
        ]
        for c in cases:
            cleaned = filter_leaked_protocol(c)
            assert "<DSML" not in cleaned and "<dsml" not in cleaned, f"Failed on: {c}"

    def test_stream_filter_split_across_chunks(self):
        flt = StreamProtocolFilter()
        chunks = [
            "Here is the text ",
            "<D",
            "SML",
            "tool_calls>",
            "<DSMLinvoke name=\"write_file\">",
            "{\"path\": \"foo.py\", \"content\": \"data\"}",
            "</DSMLinvoke>",
            "</DSMLtool_calls>",
            " done.",
        ]
        emitted = []
        for ch in chunks:
            out = flt.feed(ch)
            if out:
                emitted.append(out)
        out = flt.flush()
        if out:
            emitted.append(out)
        full = "".join(emitted)
        assert "<DSML" not in full
        assert "write_file" not in full
        assert "foo.py" not in full
        assert "Here is the text" in full
        assert "done." in full

    def test_stream_filter_dangling_open_block_flushed_safely(self):
        flt = StreamProtocolFilter()
        chunks = [
            "Result: ",
            "<DSMLtool_calls><DSMLinvoke name=\"bash\">broken stream without end tag",
        ]
        emitted = []
        for ch in chunks:
            out = flt.feed(ch)
            if out:
                emitted.append(out)
        out = flt.flush()
        if out:
            emitted.append(out)
        full = "".join(emitted)
        assert "<DSML" not in full
        assert "broken stream" not in full
        assert "Result: " in full


class TestNarrativeValidationDSML:
    def test_dsml_in_narrative_detected_as_violation(self):
        narrative = 'I noticed <DSMLinvoke name="cat">{"file":"log"}</DSMLinvoke> in output'
        valid, violations = validate_narrative_text(narrative, language="sv")
        assert not valid
        assert "raw_protocol_leakage" in violations

    def test_repair_narrative_prose_strips_dsml(self):
        narrative = 'hund ser att <DSMLtool_calls><DSMLinvoke name="grep">q</DSMLinvoke></DSMLtool_calls> filen är klar.'
        repaired = repair_narrative_prose(narrative, language="sv")
        assert "<DSML" not in repaired
        assert "grep" not in repaired
        assert "filen är klar." in repaired

    def test_preserves_legitimate_code_blocks_with_dsml_text(self):
        response = (
            "hund förklarar protokollet:\n\n"
            "```xml\n"
            "<DSMLtool_calls>\n"
            '  <DSMLinvoke name="example">\n'
            "  </DSMLinvoke>\n"
            "</DSMLtool_calls>\n"
            "```\n\n"
            "Detta är ett exempel."
        )
        final_text, result = validate_and_repair_response(response, language="sv")
        assert "```xml\n<DSMLtool_calls>" in final_text
        assert "hund förklarar protokollet:" in final_text
        assert "Detta är ett exempel." in final_text
