"""Multi-provider LLM gateway (Task 6 of the enterprise upgrade).

Supports Groq, OpenAI, Gemini, Anthropic and Ollama. Providers are
lazily instantiated (only the active one is loaded) and every call is
timed so the UI can display latency and token usage. Falls back to
Groq when the selected provider has no API key configured.
"""
import os
import re
import time

from dotenv import load_dotenv

from config.settings import fallback_model

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
    # GPT-OSS 20B replaces the decommissioned Llama 3.x default on Groq.
    "groq": "openai/gpt-oss-20b",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "anthropic": "claude-3-5-sonnet-latest",
    "ollama": "llama3.2",
}

# Matches complete <think>...</think> blocks (multiline, repeated).
_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)


def strip_think_blocks(text):
    """Remove the model's internal <think>...</think> reasoning.

    The visible answer is preserved exactly; only the reasoning block(s)
    are removed. An unclosed <think> hides the reasoning portion (and
    anything after it) so internal chain-of-thought is never shown.
    """
    if not text:
        return text
    text = _THINK_RE.sub("", text)
    # Unclosed block: drop everything from the opening tag onward.
    idx = text.lower().find("<think>")
    if idx != -1:
        text = text[:idx]
    return text.strip()


class LLMError(RuntimeError):
    """User-facing LLM failure (rate limit, unavailable model, invalid
    API key, timeout...). The message is safe to show in the UI and the
    app never crashes - agents catch it or fall back to keyword routing.
    """


# Friendly messages shown to the user, keyed by error kind. The generic
# "temporarily unavailable" wording is the catch-all.
_FRIENDLY_ERRORS = {
    "rate_limit": (
        "The AI service is busy right now (rate limit reached). "
        "Please try again in a moment or select another model."
    ),
    "model_unavailable": (
        "Selected model is temporarily unavailable. "
        "Please try another model or try again later."
    ),
    "invalid_key": (
        "Invalid API key for the selected provider. "
        "Check the API key in your environment (.env) and try again."
    ),
    "server_error": (
        "The AI service returned a server error. "
        "Please try again in a moment."
    ),
    "timeout": (
        "The AI service took too long to respond. "
        "Please try again."
    ),
    "missing_dependency": (
        "A required AI dependency is missing (for example the 'groq' "
        "package). Install the project requirements inside the app's "
        "virtual environment (e.g. `pip install -r requirements.txt` "
        "using the project's venv python, such as venv/Scripts/python.exe) "
        "and restart the app."
    ),
}

_GENERIC_ERROR = (
    "The AI service could not complete your request. "
    "Please try another model or try again later."
)


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
                # Environment problem (no API key configured at all): a
                # clear, actionable message instead of a raw exception.
                raise LLMError(
                    "No AI provider is configured. Add an API key for at "
                    "least one provider (e.g. GROQ_API_KEY) to your .env "
                    "file and restart the app."
                )
            provider = "groq"
            self.switch("groq")

        temp = temperature if temperature is not None else self.temperature
        start = time.time()
        try:
            text = self._ask_provider(provider, prompt, temp, **kwargs)
            # Reasoning-only output (e.g. a truncated <think> block) is
            # never useful: strip internal reasoning first, then retry the
            # same call once (slightly warmer) if nothing usable remains -
            # an empty "answer" would otherwise render as a blank bubble.
            text = strip_think_blocks(text)
            if not (text or "").strip():
                text = strip_think_blocks(
                    self._ask_provider(provider, prompt, temp + 0.1, **kwargs)
                )
        except Exception as exc:
            kind = self._error_kind(exc)

            # 1) Primary provider failed - retry once on Groq (unchanged).
            if provider != "groq" and "groq" in self._usable_providers:
                self.switch("groq")
                try:
                    text = self._ask_provider("groq", prompt, temp, **kwargs)
                except Exception as fb_exc:
                    raise LLMError(
                        self._friendly_message(self._error_kind(fb_exc))
                    ) from fb_exc

            # 2) Groq temporary errors (rate limit / server / timeout):
            #    wait out the throttle briefly, retry once on another
            #    configured model (e.g. 70B <-> 8B), then surface a
            #    friendly error - never a crash.
            elif provider == "groq" and kind in (
                "rate_limit", "server_error", "timeout",
            ):
                if kind == "rate_limit" and getattr(exc, "status_code", None) == 429:
                    time.sleep(10)
                try:
                    text = self._retry_with_fallback(prompt, temp, **kwargs)
                except Exception as fb_exc:
                    raise LLMError(
                        self._friendly_message(self._error_kind(fb_exc))
                    ) from fb_exc
                if text is None:
                    raise LLMError(self._friendly_message(kind)) from exc

            # 3) Deterministic failures (invalid key, unknown model, ...)
            #    and anything else: no retry, clear message only.
            else:
                raise LLMError(self._friendly_message(kind)) from exc
        finally:
            latency = int((time.time() - start) * 1000)
            self.metrics["calls"] += 1
            self.metrics["last_latency_ms"] = latency
            self.metrics["total_latency_ms"] += latency
        # Never surface the model's internal reasoning to the user.
        return strip_think_blocks(text)

    def _ask_provider(self, provider, prompt, temp, **kwargs):
        if provider == "groq":
            client = self._client or self._build_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temp,
            )
            return resp.choices[0].message.content or ""

        if provider == "openai":
            client = self._client or self._build_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temp,
            )
            return resp.choices[0].message.content or ""

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
    # Error handling (never crashes - always a friendly LLMError)
    # ------------------------------------------------------------------
    def _retry_with_fallback(self, prompt, temp, **kwargs):
        """Retry once on another model of the same provider (8B <-> 70B).

        Applies to a single call only: the caller's model is restored
        afterwards, so the user's selected model stays primary and the
        app does not auto-switch models for every request.
        """
        fallback = fallback_model(self.provider, self.model)
        if not fallback or fallback == self.model:
            return None
        original = self.model
        self.model = fallback
        try:
            return self._ask_provider(self.provider, prompt, temp, **kwargs)
        finally:
            self.model = original

    @staticmethod
    def _error_kind(exc):
        """Classify a provider exception into a friendly error category."""
        status = getattr(exc, "status_code", None)
        name = type(exc).__name__.lower()
        msg = str(exc).lower()
        # Dependency/environment problem (e.g. running with a system
        # Python that lacks the 'groq' package) - clearly distinguishable
        # from API/network/rate-limit failures so the user gets an
        # actionable message instead of a generic "service error".
        if isinstance(exc, ImportError) or "no module named" in msg \
                or "importerror" in name or "modulenotfound" in name:
            return "missing_dependency"
        if status == 401 or "invalid api key" in msg or "unauthorized" in msg:
            return "invalid_key"
        if status == 404 or "not found" in msg or "model_not_found" in msg:
            return "model_unavailable"
        if status in (413, 429) or "rate_limit" in msg or "tpm" in msg \
                or "tokens per minute" in msg or "tokens per day" in msg \
                or "request too large" in msg:
            return "rate_limit"
        if status in (500, 502, 503, 504):
            return "server_error"
        if "timeout" in name or "timed out" in msg:
            return "timeout"
        return "unknown"

    @staticmethod
    def _friendly_message(kind):
        return _FRIENDLY_ERRORS.get(kind, _GENERIC_ERROR)

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
