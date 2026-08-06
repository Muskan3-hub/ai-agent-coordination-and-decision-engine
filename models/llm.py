from dotenv import load_dotenv
import os

from models.model_manager import ModelManager
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

    def ask(self, prompt):
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
