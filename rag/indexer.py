"""TF-IDF knowledge index over a project (RAG - Task 5).

Public API:
    index_project(root, skip_dirs=None) -> KnowledgeIndex
    idx.search("where is the coordinator defined") -> [hits]
    idx.locate("CoordinatorAgent", kind="class")    -> [hits]
    idx.context_for(query, top_k=3) -> str (chunk text for LLM prompts)
"""
import math
import os
import re
import threading

# Files we never index.
SKIP_DIRS = {".git", "venv", "__pycache__", "node_modules", ".freebuff", "logs"}
SKIP_EXTS = {".db", ".pyc", ".log", ".png", ".jpg", ".jpeg", ".gif", ".xlsx", ".ico", ".woff", ".ttf", ".lock"}
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
