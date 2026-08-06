"""Tests for the RAG knowledge system (Task 5)."""
import os
import tempfile

from rag import index_project, KnowledgeIndex


def _make_project():
    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, "main.py"), "w", encoding="utf-8") as f:
        f.write('''\nclass Calculator:\n    """Adds numbers."""\n    def add(self, a, b):\n        return a + b\n''')
    with open(os.path.join(tmp, "utils.py"), "w", encoding="utf-8") as f:
        f.write('''\ndef greet(name):\n    return f"Hello {name}"\n''')
    return tmp


def test_index_and_search():
    tmp = _make_project()
    idx = index_project(tmp)
    assert len(idx.docs) >= 2
    hits = idx.search("greet function")
    assert hits, "search should return results"
    assert "utils.py" in hits[0]["file"]


def test_locate_class():
    tmp = _make_project()
    idx = index_project(tmp)
    found = idx.locate("Calculator", kind="class")
    assert found
    assert "Calculator" in found[0]["definition"]
    assert found[0]["file"] == "main.py"


def test_locate_function():
    tmp = _make_project()
    idx = index_project(tmp)
    found = idx.locate("greet", kind="def")
    assert found
    assert "def greet" in found[0]["definition"]


def test_context_for_empty_index():
    idx = KnowledgeIndex()
    assert idx.context_for("anything") == ""
    assert idx.search("anything") == []
