"""Application settings service.

Values are stored in the DB `settings` table (survive restarts) with
environment-variable fallbacks. Provider/model/temperature/theme are
editable from the Settings page; all other keys are managed by the app.
"""
import os

from database import get_db

DEFAULTS = {
    "llm_provider": "groq",
    # GPT-OSS 20B replaces the decommissioned Llama 3.x models on Groq
    # (llama-3.1-8b-instant / llama-3.3-70b-versatile are retired Aug 16).
    "llm_model": "openai/gpt-oss-20b",
    # True when the user explicitly picked a model in the UI Model
    # Selector; False keeps the automatic per-task model selection.
    "llm_model_manual": "false",
    "temperature": "0.3",
    "theme": "dark",
    "max_memory_turns": "10",
    "max_workflow_stages": "5",
    "streaming": "false",
    "github_token": "",
}

# Model options exposed in the Settings UI, keyed by provider.
PROVIDER_MODELS = {
    "groq": [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
    ],
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

# Human-friendly labels for the Model Selector UI. Keys are the exact
# model IDs from PROVIDER_MODELS - add a new entry here when a model is
# added so it shows up with a readable name.
MODEL_LABELS = {
    # Groq
    "openai/gpt-oss-20b": "GPT-OSS 20B",
    "openai/gpt-oss-120b": "GPT-OSS 120B",
    # OpenAI
    "gpt-4o": "GPT-4o",
    "gpt-4o-mini": "GPT-4o Mini",
    "gpt-3.5-turbo": "GPT-3.5 Turbo",
    # Gemini
    "gemini-2.0-flash": "Gemini 2.0 Flash",
    "gemini-1.5-flash": "Gemini 1.5 Flash",
    "gemini-1.5-pro": "Gemini 1.5 Pro",
    # Anthropic
    "claude-3-5-sonnet-latest": "Claude 3.5 Sonnet",
    "claude-3-haiku-20240307": "Claude 3 Haiku",
    # Ollama
    "llama3.2": "Llama 3.2 (Ollama)",
    "mistral": "Mistral (Ollama)",
    "codellama": "CodeLlama (Ollama)",
}


def fallback_model(provider, model):
    """Return another configured model id for the same provider, or None.

    Used for one-shot retries when the primary model hits a temporary
    rate-limit/service error (e.g. 70B -> 8B). The primary selection is
    never changed - the fallback applies to that single call only.
    """
    models = PROVIDER_MODELS.get(provider) or []
    if model in models and len(models) > 1:
        return next((m for m in models if m != model), None)
    return None


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
    def model_manual(self):
        """True when the user explicitly chose a model in the Model Selector
        (per-task automatic selection is suspended while active)."""
        return self.get("llm_model_manual", "false").lower() == "true"

    def save_model_selection(self, model, manual):
        """Persist the Model Selector choice (provider stays unchanged).

        ``manual=True`` forces every request through ``model``; ``manual=False``
        restores the automatic per-task model selection.
        """
        self.set("llm_model", model)
        self.set("llm_model_manual", "true" if manual else "false")

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
