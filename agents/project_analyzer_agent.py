import os

from prompts.project_analyzer_prompt import PROJECT_ANALYZER_PROMPT


class ProjectAnalyzer:

    def __init__(self, model, guard):
        self.model = model
        self.guard = guard

        self.ignore_dirs = {"venv", "__pycache__", ".git", "node_modules"}
        self.max_file_size = 3000

    def analyze_project(self, root="."):

        structure = []
        file_summaries = []

        for folder, dirs, files in os.walk(root):

            dirs[:] = [d for d in dirs if d not in self.ignore_dirs]

            for file in files:

                if not file.endswith(".py"):
                    continue

                path = os.path.join(folder, file)

                structure.append(path.replace(root, ""))

                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()

                    content = content[:self.max_file_size]

                    file_summaries.append(
                        {
                            "file": path.replace(root, ""),
                            "code": content,
                        }
                    )

                except Exception as e:
                    file_summaries.append(
                        {
                            "file": path.replace(root, ""),
                            "code": f"Error reading file: {e}",
                        }
                    )

        project_info = f"""
Project Structure:
{structure}

Files:
{file_summaries}
"""

        if self.guard.can_call():
            self.guard.register_call()

            prompt = PROJECT_ANALYZER_PROMPT.format_messages(
                input=project_info
            )

            return self.model.ask(prompt)

        return "LLM limit reached in ProjectAnalyzer"