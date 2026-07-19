from tools.base_tool import BaseTool
from tools.security_guard import check_file_permission
import os


class PatchTool(BaseTool):

    def execute(self, input_data):

        file_path = input_data.get("file_path")
        old_code = input_data.get("old_code")
        new_code = input_data.get("new_code")

        return self.apply_patch(
            file_path,
            old_code,
            new_code
        )


    @staticmethod
    def apply_patch(file_path, old_code, new_code):

        # Security check
        check_file_permission(file_path)


        if not os.path.exists(file_path):
            return "File not found."


        # Validate input
        if old_code is None:
            return "Old code is missing."

        if new_code is None:
            return "New code is missing."


        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()


        if old_code not in content:
            return "Old code not found in file."


        updated_content = content.replace(
            old_code,
            new_code
        )


        with open(file_path, "w", encoding="utf-8") as f:
            f.write(updated_content)


        return f"Patched: {file_path}"