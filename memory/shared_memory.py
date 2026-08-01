import json
import os


class SharedMemory:

    def __init__(self, filename="shared_memory.json"):

        self.filename = filename
        self.memory = {}

        self.load()


    def load(self):

        if os.path.exists(self.filename):

            try:

                with open(
                    self.filename,
                    "r",
                    encoding="utf-8"
                ) as f:

                    self.memory = json.load(f)

            except Exception:

                self.memory = {}



    def save(self):

        with open(
            self.filename,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                self.memory,
                f,
                indent=4
            )



    def store(self, key, value):

        self.memory[key] = value
        self.save()



    def get(self, key):

        return self.memory.get(
            key,
            ""
        )



    def get_all(self):

        return self.memory



    def clear(self):

        self.memory = {}
        self.save()