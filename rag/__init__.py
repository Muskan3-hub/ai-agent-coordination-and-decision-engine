"""RAG knowledge system (Task 5).

Indexes a project's source files and answers repository questions via
semantic retrieval - locating functions/classes, explaining
architecture, finding dependencies and bugs by similarity search.

Implementation is stdlib-only: files are chunked, tokenized, and scored
with a TF-IDF + cosine-similarity model (no external embedding service
required). An optional `sentence_transformers` model can be dropped in
later without changing the public API.
"""
from rag.indexer import KnowledgeIndex, index_project

__all__ = ["KnowledgeIndex", "index_project"]
