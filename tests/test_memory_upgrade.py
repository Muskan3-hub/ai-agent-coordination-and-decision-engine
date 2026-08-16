"""Tests for the upgraded memory system (entities + summaries + context)."""
from memory.context_builder import ContextBuilder
from memory.entity_memory import EntityMemory
from memory.short_term_memory import ShortTermMemory
from memory.summary_memory import SummaryMemory


def test_entity_regex_extraction(tmp_path):
    em = EntityMemory(file_path=str(tmp_path / "entities.json"))
    n = em.update_from_turn("My name is Muskan and I use React", use_llm=False)
    assert n >= 2
    assert "Muskan" in em.get("person")
    assert any("react" in v.lower() for v in em.get("technology"))


def test_entity_persistence(tmp_path):
    path = str(tmp_path / "entities.json")
    em = EntityMemory(file_path=path)
    em.add("person", "Muskan")
    em2 = EntityMemory(file_path=path)
    assert "Muskan" in em2.get("person")


def test_entity_dedupe_case_insensitive(tmp_path):
    em = EntityMemory(file_path=str(tmp_path / "entities.json"))
    em.add("person", "Muskan")
    em.add("person", "muskan")
    assert em.get("person") == ["Muskan"]


def test_entity_context_block(tmp_path):
    em = EntityMemory(file_path=str(tmp_path / "entities.json"))
    em.add("person", "Muskan")
    block = em.context_block()
    assert "Muskan" in block


def test_summary_memory_folds_old_turns(tmp_path):
    sm = SummaryMemory(file_path=str(tmp_path / "summary.json"), max_recent=2)
    for i in range(4):
        sm.update(f"question {i}", f"answer {i}")
    assert len(sm.get_recent()) <= 2
    assert sm.get_summary(), "older turns should be folded into a summary"


def test_summary_memory_clear(tmp_path):
    sm = SummaryMemory(file_path=str(tmp_path / "summary.json"))
    sm.update("q", "a")
    sm.clear()
    assert sm.get_summary() == ""
    assert sm.get_recent() == []


def test_context_builder_combines_all_sources(tmp_path):
    stm = ShortTermMemory(file_path=str(tmp_path / "stm.json"))
    em = EntityMemory(file_path=str(tmp_path / "entities.json"))
    sm = SummaryMemory(file_path=str(tmp_path / "summary.json"))
    em.add("person", "Muskan")
    stm.add("user", "What is AI?")
    stm.add("assistant", "AI is machine intelligence.")
    sm.update("q", "a")

    cb = ContextBuilder(short_memory=stm, summary_memory=sm, entity_memory=em)
    ctx = cb.build()
    assert "Muskan" in ctx
    assert "Recent conversation" in ctx
    assert "AI is machine intelligence" in ctx


def test_context_builder_empty(tmp_path):
    cb = ContextBuilder(
        short_memory=ShortTermMemory(file_path=str(tmp_path / "stm.json")),
        summary_memory=SummaryMemory(file_path=str(tmp_path / "summary.json")),
        entity_memory=EntityMemory(file_path=str(tmp_path / "entities.json")),
    )
    assert cb.build() == "No previous conversation."


def test_context_builder_rag_block(tmp_path):
    stm = ShortTermMemory(file_path=str(tmp_path / "stm.json"))
    cb = ContextBuilder(short_memory=stm)
    ctx = cb.build(with_rag=True, rag_context="--- utils.py ---\ndef parse()")
    assert "Relevant project context" in ctx
    assert "utils.py" in ctx
