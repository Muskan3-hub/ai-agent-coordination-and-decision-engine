"""Application settings service.

Values are stored in the DB `settings` table (survive restarts) with
environment-variable fallbacks. Provider/model/temperature/theme are
editable from the Settings page; all other keys are managed by the app.
"""
import os

from database import get_db

DEFAULTS = {
    "llm_provider": "groq",
    "llm_model": "llama-3.3-70b-versatile",
    "temperature": "0.3",
    "theme": "dark",
    "max_memory_turns": "10",
    "max_workflow_stages": "5",
    "streaming": "false",
    "github_token": "",
}

# Model options exposed in the Settings UI, keyed by provider.
PROVIDER_MODELS = {
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
    "gemini": ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"],
    "anthropic": ["claude-3-5-sonnet-latest", "claude-3-haiku-20240307"],
    "ollama": ["llama3.2", "mistral", "codellama"],
}

ENV_KEYS = {
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "ollama": "OLLAMA_BASE_URL",
}


class Settings:
    """DB-backed key/value settings with env fallbacks."""

    def __init__(self, db=None):
        self.db = db or get_db()

    def get(self, key, default=None):
        if default is None:
            default = DEFAULTS.get(key)
        return self.db.get_setting(key, default)

    def set(self, key, value):
        self.db.set_setting(key, str(value))

    # ------------------------------------------------------------------
    # Typed convenience accessors
    # ------------------------------------------------------------------
    @property
    def provider(self):
        return self.get("llm_provider", "groq")

    @property
    def model(self):
        return self.get("llm_model", DEFAULTS["llm_model"])

    @property
    def temperature(self):
        try:
            return float(self.get("temperature", "0.3"))
        except (TypeError, ValueError):
            return 0.3

    @property
    def theme(self):
        return self.get("theme", "dark")

    @property
    def streaming(self):
        return self.get("streaming", "false").lower() == "true"

    def provider_api_key(self, provider=None):
        """Return the env API key for a provider, or None."""
        provider = provider or self.provider
        env_key = ENV_KEYS.get(provider)
        return os.getenv(env_key) if env_key else None

    def save_provider_settings(self, provider, model, temperature):
        self.set("llm_provider", provider)
        self.set("llm_model", model)
        self.set("temperature", str(temperature))
