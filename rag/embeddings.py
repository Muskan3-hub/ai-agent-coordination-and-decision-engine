"""Embedding providers for the RAG pipeline.

Two implementations behind one interface (``embed(text) -> list[float]``):

- ``OpenAIEmbedder`` — uses the OpenAI embeddings API when an
  ``OPENAI_API_KEY`` is present (semantic vectors, best quality).
- ``LocalEmbedder`` — deterministic, dependency-free hashing embedder
  (character n-grams projected into a dense vector). Always available,
  fully offline, and stable within a process.

``get_embedder()`` returns the best available provider.
"""
import math
import os
import re
import zlib

EMBEDDING_DIM = 384


def _ngrams(text: str, n: int):
    for i in range(len(text) - n + 1):
        yield text[i:i + n]


class LocalEmbedder:
    """Offline character-n-gram hashing embedder (deterministic)."""

    def __init__(self, dim: int = EMBEDDING_DIM):
        self.dim = dim
        self.name = "local-hash"

    def embed(self, text) -> list:
        text = re.sub(r"\s+", " ", (text or "")).lower()[:20000]
        vec = [0.0] * self.dim
        for n in (1, 2, 3):
            for gram in _ngrams(text, n):
                # zlib.crc32 keeps the mapping stable across processes
                # (built-in hash() is salted per process).
                vec[zlib.crc32(gram.encode("utf-8")) % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts) -> list:
        return [self.embed(t) for t in texts]


class OpenAIEmbedder:
    """Semantic embeddings via the OpenAI API (falls back on failure)."""

    def __init__(self, model: str = "text-embedding-3-small", dim: int = 384):
        from openai import OpenAI  # lazy import

        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = model
        self.dim = dim
        self.name = "openai"

    def embed(self, text) -> list:
        resp = self.client.embeddings.create(
            model=self.model, input=(text or "")[:8000]
        )
        return resp.data[0].embedding

    def embed_documents(self, texts) -> list:
        if not texts:
            return []
        # Batch in chunks of 100 to stay inside API limits.
        out = []
        for i in range(0, len(texts), 100):
            batch = [(t or "")[:8000] for t in texts[i:i + 100]]
            resp = self.client.embeddings.create(model=self.model, input=batch)
            out.extend(d.embedding for d in resp.data)
        return out


def get_embedder():
    """Best available embedder: OpenAI when a key exists, else local."""
    if os.getenv("OPENAI_API_KEY"):
        try:
            return OpenAIEmbedder()
        except Exception:
            pass
    return LocalEmbedder()
