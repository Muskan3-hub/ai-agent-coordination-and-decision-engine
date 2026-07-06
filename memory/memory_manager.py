import json
import os


class MemoryManager:

    def __init__(self, filename="memory.json"):

        self.filename = filename
        self.history = []

        self.load()

    def load(self):

        if os.path.exists(self.filename):

            try:

                with open(self.filename, "r", encoding="utf-8") as f:
                    self.history = json.load(f)

            except Exception:
                self.history = []

    def save(self):

        with open(self.filename, "w", encoding="utf-8") as f:
            json.dump(self.history, f, indent=4)

    def add(self, user_input, response):

        self.history.append({
            "user": user_input,
            "assistant": response
        })

        self.save()

    def get_history(self):
        return self.history

    def get_recent_context(self, limit=3):

        if not self.history:
            return ""

        context = ""

        for item in self.history[-limit:]:

            context += (
                f"User: {item['user']}\n"
                f"Assistant: {item['assistant']}\n\n"
            )

        return context

    def clear(self):

        self.history = []

        self.save()