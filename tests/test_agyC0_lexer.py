"""agyC/0 — Spår 7 lexer-scope: bold per response-block, prose-bold = class:strong.

REV3.3-matris: "Ett ensamt obalanserat ** i ett tidigare block färgar inte text
i senare block"; krav 4: semantisk accent skild från dekorativ rosa.
"""
from prompt_toolkit.document import Document

from hund.ui.fullscreen import ResponseBlockRegistry, _OutputLexer, _parse_semantic_line


def _lex(doc_text: str, registry: ResponseBlockRegistry):
    lexer = _OutputLexer(block_registry=registry)
    get_line_style = lexer.lex_document(Document(doc_text))
    return get_line_style


def test_unbalanced_bold_in_earlier_block_does_not_colour_later_block():
    registry = ResponseBlockRegistry()
    registry.register_or_update(1, start_line=0, line_count=3, line_metadata={})
    registry.register_or_update(2, start_line=4, line_count=2, line_metadata={})
    doc_text = "turn one\nwith leak **\nend turn\n\nplain prose line\nstill plain"
    get_line = _lex(doc_text, registry)
    later_tokens = get_line(5)
    assert later_tokens is not None
    assert not any(t[0] == "class:label" for t in later_tokens)
    assert not any(t[0] == "class:strong" for t in later_tokens)


def test_inline_bold_in_prose_is_strong_not_pink_label():
    tokens = _parse_semantic_line("Here is **bold emphasis** in prose.")
    labels = [t for t in tokens if t[0] == "class:label"]
    strongs = [t for t in tokens if t[0] == "class:strong"]
    assert ("class:strong", "bold emphasis") in strongs
    assert labels == []


def test_lead_in_label_stays_label():
    tokens = _parse_semantic_line("Ansvar: lista saker.")
    assert any(t[0] == "class:label" and "Ansvar" in t[1] for t in tokens)


def test_runaway_bold_uses_strong_fail_safe():
    # A line inside an open bold region should render strong (bright), not pink.
    tokens = _parse_semantic_line("text still inside bold region", bold_open=True)
    assert tokens and tokens[0][0] == "class:strong"


def test_theme_style_map_has_strong_high_contrast():
    from hund.ui import theme

    for skin_name in theme.theme_names():
        st = theme.make_pt_style(skin_name)
        assert st is not None
        rules = dict(st.style_rules)
        assert "strong" in rules, f"{skin_name} missing class:strong style"
        assert "meta_accent" not in rules["strong"], f"{skin_name} strong must not be pink"
