import re


class DecisionEngine:

    def __init__(self):

        self.debug_keywords = [
            "debug",
            "fix",
            "bug",
            "error",
            "traceback",
            "exception"
        ]

        self.doc_keywords = [
            "explain",
            "documentation",
            "document",
            "comment",
            "describe"
        ]

        self.planner_keywords = [
            "plan",
            "planning",
            "design",
            "roadmap",
            "workflow",
            "architecture"
        ]

        self.project_keywords = [
            "analyze",
            "analysis",
            "project",
            "structure",
            "codebase"
        ]

        self.execution_keywords = [
            "run",
            "execute",
            "test",
            "output"
        ]

        self.patch_keywords = [
            "patch",
            "modify",
            "replace",
            "change",
            "update"
        ]

        self.file_keywords = [
            "read file",
            "write file",
            "delete file",
            "create file",
            "open file",
            "save file"
        ]

        self.github_keywords = [
            "github",
            "repository",
            "repo",
            "stars",
            "forks"
        ]

    def decide(self, task):

        task_lower = task.lower()

        if self.is_github_task(task_lower):
            return "github"

        elif self.is_project_task(task_lower):
            return "project"

        elif self.is_debug_task(task_lower):
            return "debug"

        elif self.is_documentation_task(task_lower):
            return "documentation"

        elif self.is_planner_task(task_lower):
            return "planner"

        elif self.is_execution_task(task_lower):
            return "execution"

        elif self.is_patch_task(task_lower):
            return "patch"

        elif self.is_file_task(task_lower):
            return "file"

        return "coding"

    # -------------------------
    # Individual decision methods
    # -------------------------

    def is_github_task(self, task):

        return any(word in task for word in self.github_keywords)

    def is_project_task(self, task):

        return any(word in task for word in self.project_keywords)

    def is_debug_task(self, task):

        return any(word in task for word in self.debug_keywords)

    def is_documentation_task(self, task):

        return any(word in task for word in self.doc_keywords)

    def is_planner_task(self, task):

        return any(word in task for word in self.planner_keywords)

    def is_execution_task(self, task):

        return any(word in task for word in self.execution_keywords)

    def is_patch_task(self, task):

        return any(word in task for word in self.patch_keywords)

    def is_file_task(self, task):

        return (
            re.search(
                r"\b[\w\-]+\.(py|txt|md|json|csv)\b",
                task
            )
            or any(word in task for word in self.file_keywords)
        )