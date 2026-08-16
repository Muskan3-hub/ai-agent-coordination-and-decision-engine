"""RAG knowledge index over a project (Task 5, upgraded).

Two retrieval models share the same public shape:

- ``KnowledgeIndex`` — TF-IDF + cosine (fast, deterministic, stdlib-only).
- ``VectorIndex`` — embedding-based semantic search with code-aware
  chunking, source ranking and conversation-aware retrieval. This is
  the production retrieval pipeline used by the assistant.

Public API:
    index_project(root, skip_dirs=None) -> KnowledgeIndex
    idx.search("where is the coordinator defined") -> [hits]
    idx.locate("CoordinatorAgent", kind="class")    -> [hits]
    idx.context_for(query, top_k=3) -> str (chunk text for LLM prompts)
    VectorIndex().context_for(query, history=[...]) -> str
"""
import math
import os
import re
import threading

from rag.embeddings import get_embedder

# Files we never index.
SKIP_DIRS = {".git", "venv", "__pycache__", "node_modules", ".freebuff", "logs"}
SKIP_EXTS = {".db", ".pyc", ".log", ".png", ".jpg", ".jpeg", ".gif", ".xlsx", ".ico", ".woff", ".ttf", ".lock"}
# Runtime state dumps are not project knowledge - they must never leak
# into retrieved context (they also pollute scores for common queries).
SKIP_FILES = {
    "shared_memory.json", "short_term_memory.json",
    "entity_memory.json", "summary_memory.json",
}
MAX_FILE_BYTES = 512 * 1024

_WORD_RE = re.compile(r"[a-z0-9_]+")


def _tokenize(text):
    """Lowercase word tokens (words + snake_case parts)."""
    tokens = _WORD_RE.findall(text.lower())
    out = []
    for tok in tokens:
        out.append(tok)
        out.extend(tok.split("_"))
    return out


def _chunk_lines(text, chunk_size=120, overlap=20):
    """Split text into overlapping line chunks."""
    lines = text.splitlines()
    if len(lines) <= chunk_size:
        return [text]
    chunks = []
    step = max(1, chunk_size - overlap)
    for start in range(0, len(lines), step):
        chunks.append("\n".join(lines[start:start + chunk_size]))
    return chunks


class KnowledgeIndex:
    """In-memory TF-IDF index over the project's source files."""

    def __init__(self):
        self.docs = []          # list of {"file","line_start","text"}
        self._df = {}           # term -> # docs containing it
        self._tf = []           # per-doc term frequency dict
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------
    def add_document(self, file_rel, text, chunk_size=120, overlap=20):
        with self._lock:
            for i, chunk in enumerate(_chunk_lines(text, chunk_size, overlap)):
                line_start = (i * max(1, chunk_size - overlap)) + 1
                doc_id = len(self.docs)
                self.docs.append({
                    "file": file_rel,
                    "line_start": line_start,
                    "text": chunk,
                })
                tf = {}
                for term in _tokenize(chunk):
                    tf[term] = tf.get(term, 0) + 1
                self._tf.append(tf)
                for term in set(tf):
                    self._df[term] = self._df.get(term, 0) + 1

    def index_directory(self, root, skip_dirs=None, extensions=None):
        """Index every text file under `root` (bounded)."""
        skip = set(SKIP_DIRS) | set(skip_dirs or [])
        extensions = extensions or {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".html", ".css", ".js"}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for name in filenames:
                if name in SKIP_FILES:
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext in SKIP_EXTS or (extensions and ext not in extensions):
                    continue
                full = os.path.join(dirpath, name)
                if os.path.getsize(full) > MAX_FILE_BYTES:
                    continue
                try:
                    with open(full, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read()
                except OSError:
                    continue
                rel = os.path.relpath(full, root)
                self.add_document(rel, text)
        return len(self.docs)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def _idf(self, term):
        n = self._df.get(term, 0)
        return math.log((1 + len(self.docs)) / (1 + n)) + 1 if self.docs else 0

    def _score(self, query_terms):
        """Return sorted (score, doc_index) for a token query."""
        if not self.docs:
            return []
        q_tf = {}
        for t in query_terms:
            q_tf[t] = q_tf.get(t, 0) + 1
        q_norm = math.sqrt(sum(v * v for v in q_tf.values())) or 1.0

        scored = []
        for doc_id, tf in enumerate(self._tf):
            dot = 0.0
            for term, qv in q_tf.items():
                tv = tf.get(term, 0)
                if tv:
                    dot += qv * tv * self._idf(term)
            if dot == 0:
                continue
            d_norm = math.sqrt(sum(v * v * self._idf(t) ** 2 for t, v in tf.items())) or 1.0
            scored.append((dot / (q_norm * d_norm), doc_id))
        scored.sort(key=lambda x: -x[0])
        return scored

    def search(self, query, top_k=5, min_score=0.02):
        terms = _tokenize(query)
        if not terms:
            return []
        results = []
        for score, doc_id in self._score(terms)[:top_k]:
            if score < min_score:
                continue
            doc = self.docs[doc_id]
            results.append({
                "file": doc["file"],
                "line_start": doc["line_start"],
                "score": round(score, 4),
                "snippet": doc["text"][:600],
            })
        return results

    def locate(self, name, kind=None, top_k=5):
        """Locate a function/class definition by name."""
        name_l = name.lower()
        found = []
        for doc_id, doc in enumerate(self.docs):
            for line_no, line in enumerate(doc["text"].splitlines(), start=doc["line_start"]):
                stripped = line.strip()
                if kind and not stripped.startswith(kind + " "):
                    continue
                if stripped.startswith(("def ", "class ")):
                    if re.search(r"\b" + re.escape(name_l) + r"\b", stripped.lower()):
                        found.append({
                            "file": doc["file"],
                            "line": line_no,
                            "definition": stripped[:140],
                        })
                        break
        return found[:top_k]

    def context_for(self, query, top_k=3):
        """Return retrieved chunks formatted for an LLM prompt."""
        hits = self.search(query, top_k=top_k)
        if not hits:
            return ""
        parts = []
        for h in hits:
            parts.append(f"--- {h['file']}:{h['line_start']} ---\n{h['snippet']}")
        return "\n\n".join(parts)


def index_project(root=".", skip_dirs=None, extensions=None):
    """Convenience: build a KnowledgeIndex for a project root."""
    idx = KnowledgeIndex()
    idx.index_directory(root, skip_dirs=skip_dirs, extensions=extensions)
    return idx


# ======================================================================
# VectorIndex - embedding-based semantic retrieval
# ======================================================================


def _history_text(history):
    """Normalize a conversation history (short-memory dicts or tuples)."""
    if not history:
        return ""
    parts = []
    for entry in history[-4:]:
        if isinstance(entry, dict):
            role = entry.get("role", "user")
            text = entry.get("message") or entry.get("content") or ""
        elif isinstance(entry, (tuple, list)) and len(entry) >= 2:
            role, text = entry[0], entry[1]
        else:
            role, text = "user", str(entry)
        parts.append(f"{role}: {text}")
    return "\n".join(parts)


class VectorIndex:
    """Embedding-based semantic index with code-aware chunking.

    Retrieval is conversation-aware: ``context_for`` accepts the recent
    conversation so follow-up questions ("give one example", "make it
    async") retrieve against the expanded query rather than the bare
    follow-up text.
    """

    def __init__(self, embedder=None, chunk_size=140, overlap=24):
        self.embedder = embedder or get_embedder()
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.docs = []      # [{"file", "line_start", "text"}]
        self.vectors = []   # [list[float]] (normalized)
        self._lock = threading.Lock()
        # Query-embedding cache (Milestone 4 - performance). Follow-up
        # questions are expanded with the conversation, so repeated
        # phrasing re-embeds the same query; cache the last N distinct
        # queries to skip the embedder call.
        self._query_cache = {}
        self._QUERY_CACHE_MAX = 64

    # ------------------------------------------------------------------
    # Chunking (code-aware: prefer class/def boundaries)
    # ------------------------------------------------------------------
    def _split_into_chunks(self, text):
        """Return [(chunk_text, line_start), ...] for a source file."""
        lines = text.splitlines() or [""]
        if len(lines) <= self.chunk_size:
            return [(text, 1)]

        bounds = [
            i for i, ln in enumerate(lines)
            if re.match(r"^\s*(class |def |async def )", ln)
        ]
        pieces = []
        start = 0
        for i in bounds[1:]:
            if i > start:
                pieces.append((start, i))
            start = i
        pieces.append((start, len(lines)))

        # Merge adjacent small pieces up to chunk_size for coherent context.
        merged = []
        buf, buf_start = "", 0
        for a, b in pieces:
            piece = "\n".join(lines[a:b])
            if buf and len(buf.splitlines()) + (b - a) > self.chunk_size:
                merged.append((buf, buf_start))
                buf, buf_start = piece, a + 1
            elif buf:
                buf = buf + "\n" + piece
            else:
                buf, buf_start = piece, a + 1
        if buf:
            merged.append((buf, buf_start))

        out = []
        for chunk_text, ls in merged:
            seg = chunk_text.splitlines()
            if len(seg) <= self.chunk_size:
                out.append((chunk_text, ls))
            else:
                step = max(1, self.chunk_size - self.overlap)
                for s in range(0, len(seg), step):
                    out.append(("\n".join(seg[s:s + self.chunk_size]), ls + s))
        return out or [(text, 1)]

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------
    def add_document(self, file_rel, text):
        with self._lock:
            for chunk, line_start in self._split_into_chunks(text):
                self.docs.append({
                    "file": file_rel,
                    "line_start": line_start,
                    "text": chunk,
                })
                self.vectors.append(self.embedder.embed(chunk))

    def index_directory(self, root, skip_dirs=None, extensions=None):
        """Index every text file under `root` (bounded)."""
        skip = set(SKIP_DIRS) | set(skip_dirs or [])
        extensions = extensions or {
            ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml",
            ".ini", ".html", ".css", ".js", ".ts", ".jsx", ".tsx", ".java",
        }
        count = 0
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for name in filenames:
                if name in SKIP_FILES:
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext in SKIP_EXTS or (extensions and ext not in extensions):
                    continue
                full = os.path.join(dirpath, name)
                if os.path.getsize(full) > MAX_FILE_BYTES:
                    continue
                try:
                    with open(full, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read()
                except OSError:
                    continue
                rel = os.path.relpath(full, root)
                self.add_document(rel, text)
                count += 1
        return len(self.docs)

    # ------------------------------------------------------------------
    # Retrieval (semantic + ranked)
    # ------------------------------------------------------------------
    def search(self, query, top_k=5, min_score=0.10):
        """Return ranked hits for a query: [{file, line_start, score, snippet}]"""
        qv = self._query_cache.get(query)
        if qv is None:
            qv = self.embedder.embed(query)
            if len(self._query_cache) >= self._QUERY_CACHE_MAX:
                self._query_cache.clear()
            self._query_cache[query] = qv
        scored = []
        for doc_id, vec in enumerate(self.vectors):
            # Both vectors are normalized -> dot product is cosine similarity.
            dot = sum(a * b for a, b in zip(qv, vec))
            if dot >= min_score:
                scored.append((dot, doc_id))
        scored.sort(key=lambda x: -x[0])
        results = []
        for score, doc_id in scored[:top_k]:
            doc = self.docs[doc_id]
            results.append({
                "file": doc["file"],
                "line_start": doc["line_start"],
                "score": round(score, 4),
                "snippet": doc["text"][:600],
            })
        return results

    def context_for(self, query, top_k=3, history=None):
        """Return retrieved chunks formatted for an LLM prompt.

        When ``history`` is provided the query is expanded with the most
        recent turns so follow-up questions retrieve relevant context.
        """
        expanded = query
        if history:
            recent = _history_text(history)
            if recent:
                expanded = f"{recent}\n\nFollow-up: {query}"
        hits = self.search(expanded, top_k=top_k)
        if not hits:
            return ""
        parts = []
        if history:
            parts.append(f"Conversation:\n{_history_text(history)}")
        for h in hits:
            parts.append(f"--- {h['file']}:{h['line_start']} (score {h['score']}) ---\n{h['snippet']}")
        return "\n\n".join(parts)

    def __len__(self):
        return len(self.docs)
