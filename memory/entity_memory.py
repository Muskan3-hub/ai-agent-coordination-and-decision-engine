"""Entity memory - persistent knowledge about the user.

Remembers the things that make conversations feel personal and context
aware: names, favorite technologies, projects, repositories, languages
and preferences. Values persist in ``memory/entities.json``.

Extraction is regex-first (deterministic, offline) with an optional
LLM pass when a model is provided and the guard allows it.
"""
import json
import os
import re

ENTITIES_FILE = os.path.join(os.path.dirname(__file__), "entities.json")

CATEGORIES = [
    "person", "technology", "project", "repository", "preference", "language",
]
CATEGORY_LABELS = {
    "person": "About you",
    "technology": "Technologies you use",
    "project": "Your projects",
    "repository": "Repositories",
    "preference": "Your preferences",
    "language": "Programming languages",
}

# (category, compiled regex) - ordered; first match group is the value.
_PATTERNS = [
    ("person", re.compile(r"\bmy name is ([A-Za-z][\w\-]*)(?: ([A-Za-z][\w\-]*))?", re.I)),
    ("person", re.compile(r"\b(?:you can )?call me ([A-Za-z][\w\-]*)(?: ([A-Za-z][\w\-]*))?", re.I)),
    ("preference", re.compile(r"\bi (?:really )?(like|love|prefer|hate) ([\w .,+#\-]{1,40})", re.I)),
    ("preference", re.compile(r"\bmy favourite (?:thing|color|colour|food|movie) is ([\w .,+#\-]{1,40})", re.I)),
    ("preference", re.compile(r"\bmy favorite (?:thing|color|colour|food|movie) is ([\w .,+#\-]{1,40})", re.I)),
    ("technology", re.compile(r"\bi (?:use|work with|build with|am learning|am using) ([\w .,+#\-]{1,40})", re.I)),
    ("technology", re.compile(r"\b(?:i code|i develop|i build) with ([\w .,+#\-]{1,40})", re.I)),
    ("project", re.compile(r"\bmy project (?:is|called|name is) ([\w\-./ ]{1,60})", re.I)),
    ("project", re.compile(r"\bthe project (?:is|called|name is) ([\w\-./ ]{1,60})", re.I)),
    ("repository", re.compile(r"\brepo(?:sitory)?(?: name)? (?:is|called) ([\w\-./]{1,80})", re.I)),
    ("repository", re.compile(r"\bgithub(?:\.com)?[:/\s]+([\w\-]+/[\w\-]+)")),
    ("language", re.compile(r"\bmy favorite language is ([\w+#.\- ]{1,30})", re.I)),
    ("language", re.compile(r"\bfavourite programming language is ([\w+#.\- ]{1,30})", re.I)),
    ("language", re.compile(r"\bi (?:program|code|write) in ([\w+#.\- ]{1,30})", re.I)),
]


def _clean(value):
    """Strip trailing conjunctions/punctuation from an extracted value."""
    value = re.sub(r"\s+(and|but|\.|,)$", "", value.strip())
    return value.strip(" .,:;!?").strip()


class EntityMemory:
    """Persistent per-user knowledge with dedupe and capping."""

    def __init__(self, file_path=None):
        self.file = file_path or ENTITIES_FILE
        self.entities = {c: [] for c in CATEGORIES}
        self._load()

    # ------------------------- persistence -------------------------
    def _load(self):
        try:
            with open(self.file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        for cat in CATEGORIES:
            items = data.get(cat) or []
            self.entities[cat] = [str(i) for i in items if str(i).strip()]

    def _save(self):
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(self.entities, f, indent=4)

    # ------------------------- CRUD -------------------------
    def add(self, category, value):
        value = _clean(str(value))
        if not value or category not in self.entities:
            return
        value = value[:120]
        low = value.lower()
        existing = [v for v in self.entities[category] if v.lower() == low]
        if existing:
            return
        self.entities[category].append(value)
        self.entities[category] = self.entities[category][-30:]  # cap
        self._save()

    def get(self, category=None):
        if category:
            return list(self.entities.get(category, []))
        return {c: list(v) for c, v in self.entities.items()}

    def clear(self):
        self.entities = {c: [] for c in CATEGORIES}
        self._save()

    # ------------------------- extraction -------------------------
    def extract_from_text(self, text):
        """Regex extraction: [(category, value), ...]."""
        if not text:
            return []
        found = []
        for cat, pattern in _PATTERNS:
            for m in pattern.finditer(text):
                value = _clean(m.group(1))
                if value:
                    found.append((cat, value))
        return found

    def _extract_with_llm(self, text, model=None):
        if model is None:
            return []
        prompt = (
            "Extract facts about the user from this message. Return one "
            "'category = value' per line using only these categories: "
            "person, technology, project, repository, preference, language. "
            "If there is nothing to extract, return 'none'. "
            "Example: 'My name is Muskan and I use React' -> "
            "person = Muskan\\ntechnology = React\\n\\nMessage:\\n" + text
        )
        try:
            raw = str(model.ask(prompt))
        except Exception:
            return []
        out = []
        for line in raw.splitlines():
            if "=" not in line:
                continue
            cat, _, val = line.partition("=")
            cat = cat.strip().lower()
            if cat in self.entities and _clean(val):
                out.append((cat, _clean(val)))
        return out

    def update_from_turn(self, user_msg, assistant_msg=None, model=None, use_llm=True):
        """Extract + persist entities from a user message."""
        pairs = self.extract_from_text(user_msg)
        if use_llm:
            pairs += self._extract_with_llm(user_msg, model=model)
        for cat, value in pairs:
            self.add(cat, value)
        return len(pairs)

    # ------------------------- prompt block -------------------------
    def context_block(self):
        """Human-readable block injected into agent prompts."""
        lines = []
        for cat in CATEGORIES:
            if self.entities[cat]:
                label = CATEGORY_LABELS[cat]
                values = ", ".join(self.entities[cat])
                lines.append(f"- {label}: {values}")
        return "\n".join(lines) if lines else ""
