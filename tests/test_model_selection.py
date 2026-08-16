"""Tests for the Model Selector feature.

Covers:
- the selected model actually reaching the backend for the next request
- model switching without rebuilding the coordinator (context preserved)
- per-task models staying fixed under "Auto", following the selection when manual
- the manual selection winning over the per-task split in _model_for
- friendly error handling (413/429/401) with fallback retry and no crashes
"""
import pytest

import config.settings as settings_mod
import database
import models.model_manager as mm_mod

from models.model_manager import ModelManager, LLMError
from models.llm import LLM


@pytest.fixture
def mem_settings(monkeypatch):
    """Hermetic Settings backed by an in-memory DB (no real enterprise.db)."""
    db = database.init_db(":memory:")
    monkeypatch.setattr(settings_mod, "get_db", lambda: db)
    return settings_mod.Settings(db)


class FakeAPIError(Exception):
    """Provider-style error with a Groq/OpenAI-like status_code."""

    def __init__(self, status, msg=""):
        super().__init__(msg or f"error {status}")
        self.status_code = status


def _recorder(monkeypatch, manager):
    """Replace _ask_provider with a recorder returning 'ok'."""
    calls = []

    def fake(provider, prompt, temp, **kwargs):
        calls.append((provider, manager.model, temp))
        return "ok"

    monkeypatch.setattr(manager, "_ask_provider", fake)
    return calls


# ----------------------------------------------------------------------
# Selected model reaches the backend
# ----------------------------------------------------------------------
def test_default_instance_uses_saved_model(monkeypatch, mem_settings):
    llm = LLM()
    calls = _recorder(monkeypatch, llm.manager)
    llm.ask("hello")
    provider, model, _ = calls[-1]
    assert provider == "groq"
    assert model == mem_settings.model  # default model from Settings


def test_switching_model_applies_to_next_request(monkeypatch, mem_settings):
    mem_settings.save_model_selection("openai/gpt-oss-20b", manual=True)
    llm = LLM()
    calls = _recorder(monkeypatch, llm.manager)

    llm.ask("first")
    assert calls[-1][1] == "openai/gpt-oss-20b"

    # User switches to the 120B in the Model Selector -> next call uses it.
    mem_settings.save_model_selection("openai/gpt-oss-120b", manual=True)
    llm.ask("second")
    assert calls[-1][1] == "openai/gpt-oss-120b"

    # No rebuild happened: same manager/instance kept serving.
    assert llm.manager.model == "openai/gpt-oss-120b"


# ----------------------------------------------------------------------
# Per-task instances: fixed under Auto, follow the selection when manual
# ----------------------------------------------------------------------
def test_per_task_instance_stays_fixed_under_auto(monkeypatch, mem_settings):
    # Settings default is the 120B, but the per-task chat instance is the 20B.
    mem_settings.save_model_selection("openai/gpt-oss-120b", manual=False)
    llm = LLM(model="openai/gpt-oss-20b")
    calls = _recorder(monkeypatch, llm.manager)
    llm.ask("chat question")
    assert calls[-1][1] == "openai/gpt-oss-20b"


def test_per_task_instance_follows_manual_selection(monkeypatch, mem_settings):
    mem_settings.save_model_selection("openai/gpt-oss-120b", manual=True)
    llm = LLM(model="openai/gpt-oss-20b")
    calls = _recorder(monkeypatch, llm.manager)
    llm.ask("chat question")
    assert calls[-1][1] == "openai/gpt-oss-120b"


def test_model_for_manual_returns_default(monkeypatch, mem_settings):
    from agents.coordinator import _model_for

    mem_settings.save_model_selection("openai/gpt-oss-20b", manual=True)
    default = LLM()
    got = _model_for("planner", default)
    assert got is default  # selection wins over the per-task 120B split


def test_model_for_auto_keeps_per_task_split(monkeypatch, mem_settings):
    from agents.coordinator import _model_for

    mem_settings.save_model_selection("openai/gpt-oss-120b", manual=False)
    default = LLM()
    chat = _model_for("chat", default)
    planner = _model_for("planner", default)
    assert chat.manager.model == "openai/gpt-oss-20b"
    assert planner.manager.model == "openai/gpt-oss-120b"


# ----------------------------------------------------------------------
# Error handling: retry with fallback, friendly errors, no crashes
# ----------------------------------------------------------------------
def test_413_retries_once_on_fallback_model(monkeypatch):
    m = ModelManager(provider="groq", model="openai/gpt-oss-20b")

    def flaky(provider, prompt, temp, **kwargs):
        if m.model == "openai/gpt-oss-20b":
            raise FakeAPIError(413, "Request too large ... TPM: Limit 6000")
        return "ok-from-120b"

    monkeypatch.setattr(m, "_ask_provider", flaky)
    assert m.ask("big prompt") == "ok-from-120b"
    # Primary selection restored after the one-shot fallback.
    assert m.model == "openai/gpt-oss-20b"


def test_429_raises_friendly_error(monkeypatch):
    # 429 waits out the throttle - skip the real 10s sleep in tests.
    monkeypatch.setattr(mm_mod.time, "sleep", lambda s: None)
    m = ModelManager(provider="groq", model="openai/gpt-oss-120b")

    def always_limited(provider, prompt, temp, **kwargs):
        raise FakeAPIError(429, "Rate limit reached ... tokens per day")

    monkeypatch.setattr(m, "_ask_provider", always_limited)
    with pytest.raises(LLMError) as ei:
        m.ask("hi")
    assert "busy" in str(ei.value) or "try again" in str(ei.value)


def test_invalid_key_raises_friendly_error(monkeypatch):
    m = ModelManager(provider="groq", model="openai/gpt-oss-120b")

    def bad_key(provider, prompt, temp, **kwargs):
        raise FakeAPIError(401, "Invalid API Key")

    monkeypatch.setattr(m, "_ask_provider", bad_key)
    with pytest.raises(LLMError) as ei:
        m.ask("hi")
    assert "Invalid API key" in str(ei.value)


def test_empty_completion_retries_once(monkeypatch):
    """An empty model completion is never a useful answer: the facade
    retries the same call once (slightly warmer) instead of returning a
    blank assistant bubble."""
    m = ModelManager(provider="groq", model="openai/gpt-oss-20b")
    calls = {"n": 0}

    def empty_then_answer(provider, prompt, temp, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return ""
        return "real answer"

    monkeypatch.setattr(m, "_ask_provider", empty_then_answer)
    assert m.ask("hi") == "real answer"
    assert calls["n"] == 2


def test_unknown_error_never_crashes_with_raw_exception(monkeypatch):
    m = ModelManager(provider="groq", model="openai/gpt-oss-120b")

    def boom(provider, prompt, temp, **kwargs):
        raise RuntimeError("mystery failure")

    monkeypatch.setattr(m, "_ask_provider", boom)
    with pytest.raises(LLMError):
        m.ask("hi")


def test_missing_dependency_error_is_distinct_and_actionable(monkeypatch):
    """Running with a Python that lacks the 'groq' package must produce
    an actionable dependency message - not a generic service error, and
    never a raw ImportError to the user."""
    m = ModelManager(provider="groq", model="openai/gpt-oss-120b")

    def missing_pkg(provider, prompt, temp, **kwargs):
        raise ImportError("No module named 'groq'")

    monkeypatch.setattr(m, "_ask_provider", missing_pkg)
    with pytest.raises(LLMError) as ei:
        m.ask("hi")

    msg = str(ei.value)
    assert "dependency" in msg.lower()
    assert "requirements.txt" in msg
    assert "groq" in msg
    # Distinct from API/network/rate-limit wording.
    assert "busy" not in msg.lower()

    assert ModelManager._error_kind(ImportError("No module named 'groq'")) == (
        "missing_dependency"
    )
    assert ModelManager._error_kind(ModuleNotFoundError("groq")) == (
        "missing_dependency"
    )


# ----------------------------------------------------------------------
# Response sanitization: internal <think> reasoning never reaches the UI
# ----------------------------------------------------------------------
def test_strip_think_blocks_removes_reasoning():
    from models.model_manager import strip_think_blocks

    assert strip_think_blocks(
        "<think>secret reasoning</think>The answer."
    ) == "The answer."


def test_strip_think_blocks_multiline():
    from models.model_manager import strip_think_blocks

    text = "<think>\nline one\nline two\n</think>\nThe image shows a red circle."
    assert strip_think_blocks(text) == "The image shows a red circle."


def test_strip_think_blocks_removes_all_blocks():
    from models.model_manager import strip_think_blocks

    text = "<think>a</think>First.<think>b</think>Second."
    assert strip_think_blocks(text) == "First.Second."


def test_strip_think_blocks_unclosed_hides_reasoning():
    from models.model_manager import strip_think_blocks

    text = "Visible answer.<think>this reasoning never closes"
    assert strip_think_blocks(text) == "Visible answer."


def test_strip_think_blocks_keeps_normal_text():
    from models.model_manager import strip_think_blocks

    text = "## Bugs\n\n- bug one\n- bug two\n\n```python\nprint(1)\n```"
    assert strip_think_blocks(text) == text


def test_ask_never_returns_think_reasoning(monkeypatch):
    """ModelManager.ask must strip reasoning from every provider response
    (chat, coding, docs, review, image follow-ups...)."""
    m = ModelManager(provider="groq", model="openai/gpt-oss-20b")

    def thinky(provider, prompt, temp, **kwargs):
        return (
            "<think>\nThe user wants a gradient description...\n</think>\n"
            "The image shows a gradient from red to blue."
        )

    monkeypatch.setattr(m, "_ask_provider", thinky)
    assert m.ask("What is shown in this image?") == (
        "The image shows a gradient from red to blue."
    )


def test_think_only_response_triggers_retry(monkeypatch):
    """A response that is entirely a (truncated) <think> block must not
    yield an empty bubble: the facade strips it, sees nothing usable,
    and retries once - the real answer then comes back clean."""
    m = ModelManager(provider="groq", model="openai/gpt-oss-20b")
    calls = {"n": 0}

    def think_then_answer(provider, prompt, temp, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return "<think>\nThe user wants a gradient description...\n    *   So"
        return "The image shows a gradient from red to blue."

    monkeypatch.setattr(m, "_ask_provider", think_then_answer)
    assert m.ask("What is shown in this image?") == (
        "The image shows a gradient from red to blue."
    )
    assert calls["n"] == 2
