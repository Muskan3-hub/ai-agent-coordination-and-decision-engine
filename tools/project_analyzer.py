"""Project analyzer tool - static (non-LLM) codebase intelligence."""

import os
import re
from collections import defaultdict

from tools.base_tool import BaseTool


# Common stdlib modules used to separate "python libraries" from
# built-in imports when computing the tech stack.
STDLIB_MODULES = {
    "abc", "argparse", "asyncio", "base64", "collections", "concurrent",
    "contextlib", "csv", "datetime", "decimal", "enum", "fractions",
    "functools", "glob", "hashlib", "heapq", "http", "importlib", "io",
    "itertools", "json", "logging", "math", "multiprocessing", "operator",
    "os", "pathlib", "pickle", "platform", "queue", "random", "re",
    "shelve", "shutil", "signal", "socket", "sqlite3", "ssl", "statistics",
    "string", "struct", "subprocess", "sys", "tempfile", "threading",
    "time", "traceback", "types", "typing", "unittest", "urllib", "uuid",
    "warnings", "weakref", "xml", "zipfile",
}

TECH_STACK_MARKERS = {
    "requirements.txt": "Python (pip requirements)",
    "pyproject.toml": "Python (pyproject/poetry)",
    "setup.py": "Python (setuptools)",
    "Pipfile": "Python (pipenv)",
    "package.json": "Node.js",
    "tsconfig.json": "TypeScript",
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker Compose",
    "manage.py": "Django",
    "main.py": "Python entry point",
    "index.html": "Static web frontend",
    "Makefile": "Make build system",
}


class ProjectAnalyzer(BaseTool):
    """
    Static project analysis tool.

    Walks a project and produces:
    - folder structure
    - module dependency summary (file -> imports)
    - entry point detection (__main__ / main())
    - technology stack markers
    - python libraries used (third-party imports)
    - health metrics (file count, lines, error handling, docstrings)

    The LLM-based ProjectAnalyzer agent builds the narrative report on
    top of this data.
    """

    def __init__(self):
        self.ignore_dirs = {
            "venv", "__pycache__", ".git", "node_modules", ".freebuff",
            "dist", "build", ".idea", ".vscode", "assets", "memory",
        }
        self.max_file_size = 3000  # important for speed

    def execute(self, input_data):
        root = input_data.get("root", ".")
        return self.analyze_project(root)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def analyze_project(self, root="."):
        structure = []
        file_summaries = []
        module_deps = defaultdict(list)
        entry_points = []
        libraries = set()
        tech_stack = set()
        total_chars = 0
        total_lines = 0
        py_count = 0
        try_count = 0
        docstring_files = 0
        has_tests = False

        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in self.ignore_dirs]

            for file in files:
                path = os.path.join(folder, file)
                # os.path.relpath (NOT str.replace) so root="." never
                # strips dots from filenames ("app.py" -> "appy").
                rel_path = os.path.relpath(path, root) or file
                structure.append(rel_path)

                # Detect test files anywhere in the tree
                if re.search(r"(^|[\/_])test", file.lower()):
                    has_tests = True

                if not file.endswith(".py"):
                    continue

                py_count += 1
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    continue

                total_lines += content.count("\n") + 1
                try_count += content.count("try:")
                if content.lstrip().startswith(('"""', "'''")):
                    docstring_files += 1

                # Module dependencies (imports)
                for mod in self._extract_imports(content):
                    module_deps[rel_path].append(mod)
                    if mod not in STDLIB_MODULES and mod != "__future__":
                        libraries.add(mod)

                # Entry point detection
                if self._is_entry_point(content):
                    entry_points.append(rel_path)

                # Cap content sent to the LLM
                remaining = 7000 - total_chars
                if remaining < 200 or len(file_summaries) >= 8:
                    continue
                snippet = content[: min(self.max_file_size, remaining)]
                total_chars += len(snippet)
                file_summaries.append({"file": rel_path, "code": snippet})

        # Tech stack markers at the root
        for marker, tech in TECH_STACK_MARKERS.items():
            if os.path.exists(os.path.join(root, marker)):
                tech_stack.add(tech)

        return {
            "structure": sorted(structure),
            "files": file_summaries,
            "module_dependencies": dict(module_deps),
            "entry_points": entry_points,
            "libraries": sorted(libraries),
            "tech_stack": sorted(tech_stack),
            "file_count": py_count,
            "total_lines": total_lines,
            "try_except_blocks": try_count,
            "docstring_files": docstring_files,
            "has_tests": has_tests,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_imports(content):
        """Return the top-level module names imported by this file."""
        imports = set()
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("import "):
                rest = line[len("import "):]
                for part in rest.split(","):
                    imports.add(part.split(".")[0].split(" as ")[0].strip())
            elif line.startswith("from "):
                match = re.match(r"from\s+([\w.]+)\s+import", line)
                if match:
                    imports.add(match.group(1).split(".")[0])
        return imports

    @staticmethod
    def _is_entry_point(content):
        """Heuristic: file has `if __name__ == "__main__"` or a main() def."""
        return (
            '__name__ == "__main__"' in content
            or "__name__ == '__main__'" in content
            or bool(re.search(r"^def\s+main\s*\(", content, re.MULTILINE))
        )
