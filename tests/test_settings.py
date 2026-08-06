"""Tests for the settings service."""
import database
from config.settings import Settings, PROVIDER_MODELS, ENV_KEYS


def test_settings_defaults_and_roundtrip():
    db = database.init_db(":memory:")
    s = Settings(db)
    assert s.provider == "groq"
    assert isinstance(s.temperature, float)

    s.save_provider_settings("openai", "gpt-4o", 0.7)
    assert s.provider == "openai"
    assert s.model == "gpt-4o"
    assert s.temperature == 0.7


def test_provider_models_and_env_keys_exist():
    assert "groq" in PROVIDER_MODELS
    assert "openai" in PROVIDER_MODELS
    assert "gemini" in PROVIDER_MODELS
    assert "anthropic" in PROVIDER_MODELS
    assert "ollama" in PROVIDER_MODELS
    assert ENV_KEYS["groq"] == "GROQ_API_KEY"
