
import os

class ProjectAnalyzer:

    def __init__(self):
        self.ignore_dirs = {"venv", "__pycache__", ".git", "node_modules"}
        self.max_file_size = 3000  # important for speed

    def analyze_project(self, root="."):
        structure = []
        file_summaries = []

        for folder, dirs, files in os.walk(root):

            # remove ignored folders
            dirs[:] = [d for d in dirs if d not in self.ignore_dirs]

            for file in files:
                if not file.endswith(".py"):
                    continue

                path = os.path.join(folder, file)

                # build structure
                structure.append(path.replace(root, ""))

                # read file safely
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()

                    content = content[:self.max_file_size]

                    file_summaries.append({
                        "file": path.replace(root, ""),
                        "code": content
                    })

                except Exception as e:
                    file_summaries.append({
                        "file": path.replace(root, ""),
                        "code": f"Error reading file: {e}"
                    })

        return {
            "structure": structure,
            "files": file_summaries
        }