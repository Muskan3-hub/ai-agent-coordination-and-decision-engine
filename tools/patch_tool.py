import os

class PatchTool:

    @staticmethod
    def apply_patch(file_path, old_code, new_code):

        if not os.path.exists(file_path):
            return "File not found."

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if old_code not in content:
            return "Old code not found in file."

        updated_content = content.replace(old_code, new_code)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(updated_content)

        return f"Patched: {file_path}"