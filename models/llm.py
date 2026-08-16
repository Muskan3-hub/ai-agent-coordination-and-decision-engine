from dotenv import load_dotenv
import os

from models.model_manager import ModelManager, LLMError
from config.settings import Settings

load_dotenv()


class LLM:
    """LLM facade (backward-compatible `ask` interface).

    Delegates to the multi-provider ModelManager (Groq / OpenAI / Gemini
    / Anthropic / Ollama). The active provider & model come from the
    persisted settings (Settings page) with env/DB fallbacks, so every
    agent keeps working unchanged while the platform supports switching
    models from the UI.
    """

    def __init__(self, provider=None, model=None, temperature=None):
        self.manager = ModelManager()
        # Instances created with an explicit model (per-task models like
        # the 8B/70B split) stay fixed unless the user manually selects a
        # model; the default instance always follows the saved selection.
        self._explicit_model = model is not None
        try:
            settings = Settings()
            provider = provider or settings.provider
            model = model or settings.model
            temperature = settings.temperature if temperature is None else temperature
        except Exception:
            # DB not ready (e.g. early tests) - rely on defaults.
            pass
        self.manager.switch(provider=provider, model=model, temperature=temperature)
        self.llm = self.manager

    def _sync_selection(self):
        """Follow the persisted Model Selector choice (Settings DB).

        Runs before every call so a model picked in the sidebar is used
        by the very next request - no coordinator rebuild, so all
        conversation / memory / uploaded-file context is preserved.
        """
        try:
            settings = Settings()
            # Per-task instances keep their fixed model unless the user
            # explicitly picked one (then the selection wins for all).
            if not (settings.model_manual or not self._explicit_model):
                return
            current = (
                self.manager.provider,
                self.manager.model,
                self.manager.temperature,
            )
            target = (settings.provider, settings.model, settings.temperature)
            if current != target:
                self.manager.switch(
                    provider=settings.provider,
                    model=settings.model,
                    temperature=settings.temperature,
                )
        except Exception:
            # Settings DB unavailable - keep the current configuration.
            pass

    def ask(self, prompt):
        self._sync_selection()
        # Accepts either a plain string or LangChain-style messages;
        # the underlying gateway only needs the string form.
        if isinstance(prompt, str):
            return self.manager.ask(prompt)
        # LangChain message lists: concatenate human text.
        texts = []
        for msg in prompt if isinstance(prompt, (list, tuple)) else []:
            content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
            if content:
                texts.append(str(content))
        return self.manager.ask("\n\n".join(texts))
