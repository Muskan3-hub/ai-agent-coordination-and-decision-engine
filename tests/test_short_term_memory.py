import json
import os

from memory.short_term_memory import ShortTermMemory


def test_store_and_recall_facts(tmp_path):
    mem = ShortTermMemory(file_path=str(tmp_path / "stm.json"))

    mem.store_fact("name", "Muskan")
    mem.store_fact("favorite food", "pizza")

    assert mem.get_facts() == {
        "name": "Muskan",
        "favorite food": "pizza",
    }

    matches = mem.recall("what is my name")
    assert matches == {"name": "Muskan"}

    no_match = mem.recall("what color do i like")
    assert no_match is None


def test_add_and_context_window(tmp_path):
    mem = ShortTermMemory(file_path=str(tmp_path / "stm.json"))

    for i in range(15):
        mem.add("user", f"message-{i}")

    context = mem.get_context()
    assert "message-0" not in context
    assert "message-14" in context

    messages = mem.get_messages()
    assert len(messages) == 10


def test_clear(tmp_path):
    mem = ShortTermMemory(file_path=str(tmp_path / "stm.json"))
    mem.add("user", "hello")
    mem.store_fact("name", "Muskan")
    mem.clear()
    assert mem.get_messages() == []
    assert mem.get_facts() == {}


def test_migrates_legacy_list_format(tmp_path):
    path = tmp_path / "stm.json"
    with open(path, "w") as f:
        json.dump(
            [
                {"role": "user", "message": "hi"},
                {"role": "assistant", "message": "hello!"},
            ],
            f,
        )

    mem = ShortTermMemory(file_path=str(path))
    assert len(mem.get_messages()) == 2
    assert mem.get_context() == "User: hi\n\nAssistant: hello!"
    assert mem.get_facts() == {}
