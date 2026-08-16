import json
import os
import re


class ShortTermMemory:
    """
    Short-term conversation memory.

    Stores:
    - recent conversation turns (messages window, default last 10)
    - extracted personal facts (topic -> value) for memory store/recall

    Backward compatible: the old JSON format was a plain list of
    {"role": ..., "message": ...} entries; it is migrated on load.
    """

    def __init__(self, file_path=None):
        self.file = file_path or "memory/short_term_memory.json"
        self.max_messages = 10
        self._ensure_file()

    # ------------------------- file helpers -------------------------
    def _ensure_file(self):
        if not os.path.exists(self.file):
            self._save({"messages": [], "facts": {}})

    def _load(self):
        try:
            with open(self.file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = []

        # Migrate old list format -> dict format
        if isinstance(data, list):
            data = {"messages": data, "facts": {}}

        if not isinstance(data, dict):
            data = {}

        data.setdefault("messages", [])
        data.setdefault("facts", {})

        # Only keep dict-style message entries
        data["messages"] = [
            m for m in data["messages"]
            if isinstance(m, dict) and "message" in m
        ][-self.max_messages:]

        if not isinstance(data["facts"], dict):
            data["facts"] = {}

        return data

    def _save(self, data):
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    # ------------------------- messages -------------------------
    def add(self, role, message):
        data = self._load()
        data["messages"].append({
            "role": role,
            "message": message
        })
        data["messages"] = data["messages"][-self.max_messages:]
        self._save(data)

    def get_messages(self):
        return self._load()["messages"]

    def get_context(self, limit=6):
        """
        Returns the last few turns as readable text so it can be injected
        into agent prompts as 'Previous Conversation'.
        """
        messages = self._load()["messages"][-limit:]
        if not messages:
            return "No previous conversation."

        lines = []
        for m in messages:
            role = m.get("role", "user")
            msg = m.get("message", "")
            # Cap each message so the history block can never blow past
            # the provider's per-minute token ceiling (Groq 8B: 6k TPM).
            if len(msg) > 1500:
                msg = msg[:1500] + "\n…(truncated)"
            lines.append(f"{role.capitalize()}: {msg}")
        return "\n\n".join(lines)

    # ------------------------- facts -------------------------
    def store_fact(self, topic, value):
        data = self._load()
        data["facts"][str(topic).strip().lower()] = str(value).strip()
        self._save(data)

    def get_facts(self):
        return self._load()["facts"]

    def clear_facts(self):
        data = self._load()
        data["facts"] = {}
        self._save(data)

    def recall(self, query):
        """
        Returns dict {topic: value} for facts whose topic words overlap
        with the words in the query. Returns None if no facts stored.
        """
        facts = self._load()["facts"]
        if not facts:
            return None

        q_words = set(re.findall(r"[a-z0-9]+", query.lower()))

        matches = {}
        for topic, value in facts.items():
            t_words = set(re.findall(r"[a-z0-9]+", topic.lower()))
            if q_words & t_words:
                matches[topic] = value

        return matches or None

    # ------------------------- clear -------------------------
    def clear(self):
        self._save({"messages": [], "facts": {}})
