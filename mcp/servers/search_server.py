"""Search MCP server: codebase keyword search (Task 7)."""
import os
import re

from mcp.base import MCPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Directories / files to skip while scanning.
SKIP_DIRS = {".git", "venv", "__pycache__", "node_modules", ".freebuff"}
SKIP_EXTS = {".db", ".pyc", ".log", ".png", ".jpg", ".xlsx"}


class SearchMCPServer(MCPServer):
    name = "search"

    actions = {
        "search": "Regex/keyword search across the project",
        "files": "List all source files",
        "find_symbol": "Find a function/class definition",
    }

    def _iter_files(self):
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                if os.path.splitext(name)[1].lower() in SKIP_EXTS:
                    continue
                yield os.path.join(dirpath, name)

    def _action_search(self, params):
        pattern = params.get("pattern", "")
        if not pattern:
            return {"error": "pattern is required"}
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return {"error": f"Invalid regex: {e}"}
        limit = int(params.get("limit", 50))
        results = []
        for path in self._iter_files():
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if regex.search(line):
                            rel = os.path.relpath(path, ROOT)
                            results.append({
                                "file": rel,
                                "line": i,
                                "match": line.rstrip()[:160],
                            })
                            if len(results) >= limit:
                                return results
            except OSError:
                continue
        return results

    def _action_files(self, params):
        return [os.path.relpath(p, ROOT) for p in self._iter_files()]

    def _action_find_symbol(self, params):
        name = params.get("name", "")
        if not name:
            return {"error": "name is required"}
        found = []
        for path in self._iter_files():
            if not path.endswith(".py"):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        stripped = line.strip()
                        if stripped.startswith(f"def {name}") or stripped.startswith(
                            f"class {name}"
                        ):
                            found.append({
                                "file": os.path.relpath(path, ROOT),
                                "line": i,
                                "definition": stripped[:120],
                            })
            except OSError:
                continue
        return found
