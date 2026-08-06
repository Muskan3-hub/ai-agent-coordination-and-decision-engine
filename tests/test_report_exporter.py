"""Tests for the report exporter (MD + HTML)."""
from tools.report_exporter import export, to_markdown, to_html


REPORT = {
    "title": "Code Analysis",
    "subtitle": "Enterprise report",
    "summary": ["Line one", "Line two"],
    "metrics": [("Quality", "85/100"), ("LOC", "42")],
    "sections": [("Findings", "No bugs found")],
    "tables": [("Functions", ["name", "cc"], [["add", 1]])],
    "code": "print('hi')",
}


def test_markdown_export():
    fn, content, mime = export(REPORT, "md")
    assert fn.endswith(".md")
    assert mime == "text/markdown"
    assert "Code Analysis" in content
    assert "| name | cc |" in content


def test_html_export():
    fn, content, mime = export(REPORT, "html")
    assert fn.endswith(".html")
    assert "<table>" in content
    assert "No bugs found" in content


def test_markdown_helpers():
    md = to_markdown(REPORT)
    assert md.startswith("# Code Analysis")
    html = to_html(REPORT)
    assert html.startswith("<!DOCTYPE html>")
