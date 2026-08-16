"""RAG knowledge system (Task 5, upgraded).

Indexes a project's source files and answers repository questions via
semantic retrieval - locating functions/classes, explaining
architecture, finding dependencies and bugs by similarity search.

Two retrieval models are exposed:

- ``KnowledgeIndex`` — TF-IDF + cosine (fast, stdlib-only).
- ``VectorIndex`` — embedding-based semantic search with code-aware
  chunking, source ranking and conversation-aware retrieval.
- ``RetrievalChain`` — LangChain pipeline (prompt template + LLM) on
  top of the vector index.

Embeddings come from ``rag.embeddings``: OpenAI when a key is present,
otherwise a deterministic offline hashing embedder.
"""
from rag.indexer import KnowledgeIndex, VectorIndex, index_project
from rag.retriever import RetrievalChain

__all__ = ["KnowledgeIndex", "VectorIndex", "RetrievalChain", "index_project"]
