from tools.base_tool import BaseTool
from tools.security_guard import check_file_permission
import os


class FileTool(BaseTool):

    @staticmethod
    def write_file(file_path, content):
        """Create or overwrite a file."""

        folder = os.path.dirname(file_path)

        if folder:
            os.makedirs(folder, exist_ok=True)
        

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"File saved successfully: {file_path}"


    @staticmethod
    def read_file(file_path):
        """Read a file."""

        if not os.path.exists(file_path):
            return "File not found."

        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()


    @staticmethod
    def append_file(file_path, content):
        """Add content to the end of a file."""

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(content)

        return f"Content added to {file_path}"


    @staticmethod
    def delete_file(file_path):
        """Delete a file."""

        if os.path.exists(file_path):
            os.remove(file_path)
            return f"Deleted {file_path}"

        return "File not found."
    
    def execute(self, input_data):

        action = input_data.get("action")


        if action == "read":

            return self.read_file(
                input_data["path"]
            )


        elif action == "write":

            return self.write_file(
                input_data["path"],
                input_data["content"]
            )


        elif action == "delete":

            return self.delete_file(
                input_data["path"]
            )


        return "Invalid file action"
        
        
    @staticmethod
    def exists(file_path):
        """Check whether a file exists."""

        return os.path.exists(file_path)    
    @staticmethod
    def write_multiple_files(file_blocks):
        """
        file_blocks = [
            {"path": "app.py", "content": "..."},
            {"path": "utils/helper.py", "content": "..."}
        ]
        """

        results = []

        for file in file_blocks:
            path = file["path"]
            content = file["content"]

            folder = os.path.dirname(path)

            if folder:
                os.makedirs(folder, exist_ok=True)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            results.append(f"Saved: {path}")

        return results