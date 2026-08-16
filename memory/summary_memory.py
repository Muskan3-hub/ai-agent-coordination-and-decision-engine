"""Conversation summary memory.

Keeps a small rolling window of the most recent turns plus a persistent
summary of everything older. When the window overflows, the oldest turns
are folded into the summary (via the LLM when available, otherwise a
plain-text fold). This keeps long conversations coherent without
blowing up the context injected into agent prompts.
"""
import json
import os

SUMMARY_FILE = os.path.join(os.path.dirname(__file__), "summary.json")


class SummaryMemory:
    """Rolling summary + recent-turns window, persisted to JSON."""

    def __init__(self, file_path=None, max_recent=6, max_summary_chars=5000):
        self.file = file_path or SUMMARY_FILE
        self.max_recent = max_recent
        self.max_summary_chars = max_summary_chars
        self.data = {"summary": "", "recent": []}
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
        self.data = {
            "summary": str(data.get("summary", "")),
            "recent": [t for t in data.get("recent", []) if isinstance(t, dict)][-self.max_recent:],
        }

    def _save(self):
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4)

    # ------------------------- API -------------------------
    def update(self, user_msg, assistant_msg, model=None):
        """Append a turn; fold oldest turns into the summary on overflow."""
        self.data["recent"].append(
            {"user": str(user_msg), "assistant": str(assistant_msg)}
        )
        if len(self.data["recent"]) > self.max_recent:
            self._fold(model)
        self._save()

    def _fold(self, model=None):
        overflow = self.data["recent"][:-self.max_recent]
        self.data["recent"] = self.data["recent"][-self.max_recent:]
        text = "\n".join(
            f"User: {t['user']}\nAssistant: {t['assistant'][:900]}"
            for t in overflow
        )
        if not text.strip():
            return

        if model is not None:
            try:
                new_summary = str(
                    model.ask(
                        "Summarize this conversation so far in 2-3 concise "
                        "sentences (keep names, tech, decisions):\n\n" + text
                    )
                )
            except Exception:
                new_summary = text[:1200]
        else:
            new_summary = text[:1200]

        merged = f"{self.data['summary']} {new_summary}".strip()
        self.data["summary"] = merged[:self.max_summary_chars]

    def get_summary(self):
        return self.data.get("summary", "")

    def get_recent(self, limit=None):
        limit = limit or self.max_recent
        return self.data.get("recent", [])[-limit:]

    def clear(self):
        self.data = {"summary": "", "recent": []}
        self._save()
