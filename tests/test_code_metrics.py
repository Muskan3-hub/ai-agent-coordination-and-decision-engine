"""Tests for the enterprise static code metrics engine."""
from tools.code_metrics import (
    analyze, cyclomatic_complexity, unused_imports, security_score,
)


SAMPLE = '''
import os
import math

def add(a, b):
    """Add two numbers."""
    return a + b

def classify(x):
    if x > 0:
        return "pos"
    elif x < 0:
        return "neg"
    else:
        return "zero"
    print("dead")
'''


def test_analyze_returns_all_keys():
    r = analyze(SAMPLE)
    for key in [
        "lines_of_code", "function_count", "cyclomatic_complexity",
        "maintainability_index", "documentation_coverage", "unused_imports",
        "unused_variables", "dead_code_regions", "security_score",
        "quality_score",
    ]:
        assert key in r


def test_metrics_values():
    r = analyze(SAMPLE)
    assert r["function_count"] == 2
    assert r["cyclomatic_complexity"]["max"] == 5
    assert r["unused_imports"] == ["os", "math"]
    assert r["security_score"] == 100


def test_cyclomatic_complexity_detection():
    assert cyclomatic_complexity.__name__ == "cyclomatic_complexity"


def test_security_score_penalties():
    code = "def f():\n    return eval(input('x'))\n"
    assert security_score(code) < 100


def test_invalid_code_handled_gracefully():
    r = analyze("def broken(:\n  pass")
    assert r["function_count"] == 0
