"""Tests for the Milestone 5 response-directive parser.

Word-count, difficulty, coding-style, complexity, length and output-format
requests must be detected and turned into a compact instruction block -
without ever changing routing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.response_directives import directives_block, extract_directives


def test_plain_request_has_no_directives():
    assert extract_directives("What is Artificial Intelligence?") == {}
    assert extract_directives("Write a Python function to reverse a string") == {}


def test_word_count_detection():
    assert extract_directives("Explain AI in 50 words")["word_count"] == 50
    assert extract_directives("Explain AI in 100 words.")["word_count"] == 100
    assert extract_directives("Explain it in exactly 200 words")["word_count"] == 200
    assert extract_directives("Give a 500-word summary")["word_count"] == 500
    assert extract_directives("Summarize in 5 lines")["word_count"] == 5
    assert extract_directives("Explain AI in about 80 words")["word_count"] == 80


def test_exact_word_count_flag():
    """'Exactly N words' is flagged as a strict constraint; approximate
    phrasings are not."""
    d = extract_directives("Explain it in exactly 100 words.")
    assert d["word_count"] == 100
    assert d.get("word_count_exact") is True

    d2 = extract_directives("Explain recursion for a beginner in exactly 80 words")
    assert d2["word_count"] == 80
    assert d2.get("word_count_exact") is True

    for approx in (
        "Explain AI in about 100 words",
        "Explain AI in 100 words",
        "Explain AI in around 100 words",
        "Explain AI in at most 100 words",
    ):
        d3 = extract_directives(approx)
        assert d3["word_count"] == 100
        assert not d3.get("word_count_exact"), approx


def test_exact_directives_block_says_exactly():
    d = extract_directives("Explain it in exactly 100 words.")
    block = directives_block(d)
    assert block is not None
    assert "EXACTLY 100 words" in block
    assert "approximately" not in block

    d2 = extract_directives("Explain it in 100 words.")
    block2 = directives_block(d2)
    assert "approximately 100 words" in block2


def test_difficulty_detection():
    assert extract_directives("Explain in simple words")["difficulty"] == "simple"
    assert extract_directives("Explain it for beginners")["difficulty"] == "beginner"
    assert extract_directives("Explain for a 10-year-old")["difficulty"] == "beginner"
    assert extract_directives("Explain in technical terms")["difficulty"] == "detailed"
    assert extract_directives("Explain in interview style")["difficulty"] == "interview"
    assert extract_directives("Explain in academic style")["difficulty"] == "academic"
    assert extract_directives("Explain briefly")["difficulty"] == "brief"


def test_coding_style_detection():
    assert extract_directives("Write object-oriented Python code")["code_style"] == "oop"
    assert extract_directives("Write Python code using functions")["code_style"] == "functional"
    assert extract_directives("Write production-ready code")["code_style"] == "production"
    assert extract_directives("Write optimized code")["code_style"] == "optimized"
    assert extract_directives("Write clean code")["code_style"] == "clean"
    assert extract_directives("Write simple Python code")["code_style"] == "simple"


def test_complexity_detection():
    assert extract_directives("Give a basic implementation")["complexity"] == "basic"
    assert extract_directives("Give an advanced implementation")["complexity"] == "advanced"
    assert extract_directives("Give an optimized implementation")["complexity"] == "optimized"


def test_length_detection():
    assert extract_directives("Write short code")["length"] == "short"
    assert extract_directives("Concise implementation please")["length"] == "short"
    assert extract_directives("Write fully commented code")["length"] == "detailed"
    assert extract_directives("Detailed implementation expected")["length"] == "detailed"


def test_format_detection():
    assert extract_directives("Only code, no explanation")["format"] == "code_only"
    assert extract_directives("Code without explanation")["format"] == "code_only"
    assert extract_directives(
        "Fix the bugs and give me only the corrected code."
    )["format"] == "code_only"
    assert extract_directives(
        "Give me only the optimized code."
    )["format"] == "code_only"
    assert extract_directives("Explain step by step")["format"] == "steps"
    assert extract_directives("Give the pseudocode")["format"] == "pseudocode"
    assert extract_directives("Explain in bullet points")["format"] == "bullets"
    assert extract_directives("Present it in table format")["format"] == "table"


def test_combined_directives():
    d = extract_directives(
        "Explain AI in 100 words in simple language with bullet points"
    )
    assert d["word_count"] == 100
    assert d["difficulty"] == "simple"
    assert d["format"] == "bullets"


def test_directives_block_is_compact_and_actionable():
    d = extract_directives("Explain it in 50 words for beginners")
    block = directives_block(d)
    assert block is not None
    assert "[Response requirements]" in block
    assert "approximately 50 words" in block
    assert "beginner" in block


def test_directives_block_empty_for_plain_request():
    assert directives_block({}) is None
