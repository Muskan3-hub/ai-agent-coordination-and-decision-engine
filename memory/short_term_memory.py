import json
import os


class ShortTermMemory:

    def __init__(self):
        self.file = "memory/short_term_memory.json"

        if not os.path.exists(self.file):
            with open(self.file, "w") as f:
                json.dump([], f)

    def add(self, role, message):

        with open(self.file, "r") as f:
            data = json.load(f)

        data.append({
            "role": role,
            "message": message
        })

        # Keep only last 10 messages
        data = data[-10:]

        with open(self.file, "w") as f:
            json.dump(data, f, indent=4)

    def get_context(self):

        with open(self.file, "r") as f:
            return json.load(f)

    def clear(self):

        with open(self.file, "w") as f:
            json.dump([], f, indent=4)