"""Tests for web content quality: nav_skeleton detection and rendering."""
from __future__ import annotations

from pathlib import Path

from hund.tools.types import (
    ToolKind,
    ToolResult,
    ToolStatus,
    create_error_result,
    create_success_result,
)
from hund.tools.web_open import _semantic_regions, _SemanticHTMLParser


NAV_HTML = """\
<html>
<head><title>Test Page</title></head>
<body>
<nav>
<a href="/products">Products</a>
<a href="/blog">Blog</a>
<a href="/pricing">Pricing</a>
<a href="/about">About</a>
<a href="/contact">Contact</a>
</nav>
<footer>
<a href="/privacy">Privacy</a>
<a href="/terms">Terms</a>
</footer>
</body>
</html>
"""

CONTENT_HTML = """\
<html>
<head><title>Article Page</title></head>
<body>
<nav>
<a href="/">Home</a>
<a href="/blog">Blog</a>
</nav>
<article>
<h1>How to Use Gemma 4</h1>
<p>Gemma 4 is a family of open-weight models released by Google DeepMind.</p>
<p>There are five sizes: E2B, E4B, 12B, 26B A4B, and 31B.</p>
<h2>Hardware Requirements</h2>
<p>The 12B model requires approximately 24GB of VRAM in FP16.</p>
</article>
</body>
</html>
"""


def test_nav_skeleton_detected_on_nav_only_html():
    """_semantic_regions on a nav-only HTML should produce mostly link regions, triggering NAV_SKELETON."""
    title, regions = _semantic_regions(NAV_HTML, "text/html", "https://example.com/")
    assert len(regions) >= 4

    link_count = sum(1 for r in regions if r.url is not None)
    non_link_count = len(regions) - link_count
    ratio = link_count / len(regions)

    assert ratio > 0.6, f"Expected >0.6 link ratio, got {ratio:.2f} ({link_count}/{len(regions)})"
    assert non_link_count < 2, f"Expected <2 non-link regions, got {non_link_count}"


def test_content_html_not_flagged_as_nav_skeleton():
    """A page with real content (headings + paragraphs) should NOT trigger NAV_SKELETON."""
    title, regions = _semantic_regions(CONTENT_HTML, "text/html", "https://example.com/")
    assert len(regions) >= 4

    link_count = sum(1 for r in regions if r.url is not None)
    non_link_count = len(regions) - link_count
    ratio = link_count / len(regions) if regions else 0

    # Should have content regions (headings + paragraphs)
    assert non_link_count >= 2, f"Expected >=2 non-link regions, got {non_link_count}"
    # May or may not be >0.6, but should have enough content
    content_kinds = {r.kind for r in regions if r.url is None}
    assert "heading" in content_kinds or "paragraph" in content_kinds


def test_nav_skeleton_to_llm_text_rendering():
    """ToolResult with NAV_SKELETON status renders as [nav_skeleton] with descriptive message."""
    result = create_error_result(
        ToolStatus.NAV_SKELETON,
        ToolKind.WEB_PAGE,
        raw_error="nav only",
        public_error="sidan innehåller huvudsakligen navigation — källan har inget läsbart innehåll",
    )
    rendered = result.to_llm_text()
    assert "[nav_skeleton]" in rendered
    assert "navigation" in rendered


def test_nav_skeleton_default_message():
    """NAV_SKELETON with no public_error uses the sensible default."""
    result = ToolResult(ToolStatus.NAV_SKELETON, ToolKind.WEB_PAGE)
    rendered = result.to_llm_text()
    assert "[nav_skeleton]" in rendered