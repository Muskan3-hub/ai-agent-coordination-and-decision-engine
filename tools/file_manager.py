import os

class FileManager:

    def create_file(self, filename, content):
        try:
            with open(filename, "w", encoding="utf-8") as file:
                file.write(content)
            return f"File '{filename}' created successfully."
        except Exception as e:
            return str(e)

    def read_file(self, filename):
        try:
            with open(filename, "r", encoding="utf-8") as file:
                return file.read()
        except Exception as e:
            return str(e)

    def update_file(self, filename, content):
        try:
            with open(filename, "a", encoding="utf-8") as file:
                file.write(content)
            return f"File '{filename}' updated successfully."
        except Exception as e:
            return str(e)