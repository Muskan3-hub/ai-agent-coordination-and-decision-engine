"""Multi-provider LLM gateway (Task 6 of the enterprise upgrade).

Supports Groq, OpenAI, Gemini, Anthropic and Ollama. Providers are
lazily instantiated (only the active one is loaded) and every call is
timed so the UI can display latency and token usage. Falls back to
Groq when the selected provider has no API key configured.
"""
import os
import time

from dotenv import load_dotenv

load_dotenv()

# Provider -> env var that must be set for the provider to be usable.
PROVIDER_ENV = {
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "ollama": "OLLAMA_BASE_URL",
}

MODEL_ALIASES = {
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "anthropic": "claude-3-5-sonnet-latest",
    "ollama": "llama3.2",
}


class ModelManager:
    """Single entry point for all LLM calls with metrics."""

    def __init__(self, provider=None, model=None, temperature=0.3):
        self.provider = provider or os.getenv("LLM_PROVIDER", "groq")
        self.model = model or MODEL_ALIASES.get(self.provider)
        self.temperature = temperature
        self._client = None
        # Metrics for the current session (latency ms, tokens, calls).
        self.metrics = {"calls": 0, "total_latency_ms": 0, "last_latency_ms": 0}

    # ------------------------------------------------------------------
    # Provider selection
    # ------------------------------------------------------------------
    @property
    def _usable_providers(self):
        usable = []
        for p, env in PROVIDER_ENV.items():
            if os.getenv(env):
                usable.append(p)
        return usable

    def switch(self, provider=None, model=None, temperature=None):
        """Change provider/model (no-op if the provider is unusable)."""
        if provider and provider in self._usable_providers:
            self.provider = provider
            self.model = model or MODEL_ALIASES.get(provider)
        if temperature is not None:
            self.temperature = temperature
        self._client = None  # force re-instantiation
        return self

    # ------------------------------------------------------------------
    # Client construction (lazy)
    # ------------------------------------------------------------------
    def _build_client(self):
        p = self.provider
        if p == "groq":
            from groq import Groq
            return Groq(api_key=os.getenv("GROQ_API_KEY"))
        if p == "openai":
            from openai import OpenAI
            return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        if p == "gemini":
            from google import genai
            return genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        if p == "anthropic":
            from anthropic import Anthropic
            return Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        if p == "ollama":
            # Ollama: no SDK required - use a simple HTTP client.
            return "ollama"
        raise RuntimeError(f"Unknown provider: {p}")

    # ------------------------------------------------------------------
    # Ask (main entry point)
    # ------------------------------------------------------------------
    def ask(self, prompt, temperature=None, **kwargs):
        """Run a chat prompt and return the text response.

        Tracks latency + call count in self.metrics. Falls back to Groq
        when the chosen provider has no API key.
        """
        provider = self.provider
        if provider not in self._usable_providers:
            if "groq" not in self._usable_providers:
                raise RuntimeError("No LLM provider configured (GROQ_API_KEY etc.)")
            provider = "groq"
            self.switch("groq")

        temp = temperature if temperature is not None else self.temperature
        start = time.time()
        try:
            text = self._ask_provider(provider, prompt, temp, **kwargs)
        except Exception:
            # On transient provider failure, fall back to Groq once.
            if provider != "groq" and "groq" in self._usable_providers:
                self.switch("groq")
                text = self._ask_provider("groq", prompt, temp, **kwargs)
            else:
                raise
        finally:
            latency = int((time.time() - start) * 1000)
            self.metrics["calls"] += 1
            self.metrics["last_latency_ms"] = latency
            self.metrics["total_latency_ms"] += latency
        return text

    def _ask_provider(self, provider, prompt, temp, **kwargs):
        if provider == "groq":
            client = self._client or self._build_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temp,
            )
            return resp.choices[0].message.content

        if provider == "openai":
            client = self._client or self._build_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temp,
            )
            return resp.choices[0].message.content

        if provider == "gemini":
            from google import genai
            client = self._client or self._build_client()
            resp = client.models.generate_content(
                model=self.model, contents=prompt
            )
            return resp.text

        if provider == "anthropic":
            from anthropic import Anthropic
            client = self._client or self._build_client()
            resp = client.messages.create(
                model=self.model,
                max_tokens=4096,
                temperature=temp,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(
                b.text for b in resp.content if getattr(b, "type", "") == "text"
            )

        if provider == "ollama":
            import requests
            base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            resp = requests.post(
                f"{base}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")

        raise RuntimeError(f"Unknown provider: {provider}")

    # ------------------------------------------------------------------
    # Status helpers (for the UI)
    # ------------------------------------------------------------------
    def status(self):
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "calls": self.metrics["calls"],
            "last_latency_ms": self.metrics["last_latency_ms"],
            "total_latency_ms": self.metrics["total_latency_ms"],
            "api_key_set": self.provider in self._usable_providers,
        }
