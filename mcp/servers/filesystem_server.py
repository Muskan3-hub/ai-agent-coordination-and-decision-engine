"""Filesystem MCP server: safe file operations (Task 7)."""
import os

from mcp.base import MCPServer

# Root that this server is allowed to touch (project root by default).
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class FilesystemMCPServer(MCPServer):
    name = "filesystem"

    actions = {
        "list": "List files in a directory",
        "read": "Read a file (bounded size)",
        "exists": "Check whether a path exists",
        "tree": "Show a shallow directory tree",
        "stat": "File metadata (size, mtime)",
    }

    def _safe(self, path):
        """Resolve path and ensure it stays inside ROOT."""
        full = os.path.abspath(os.path.join(ROOT, path or ""))
        # commonpath defeats prefix-match bypasses (ROOT + "_evil" etc.).
        try:
            if os.path.commonpath([full, ROOT]) != os.path.abspath(ROOT):
                raise PermissionError("Path escapes the workspace root.")
        except ValueError:
            raise PermissionError("Path escapes the workspace root.")
        return full

    def _action_list(self, params):
        path = self._safe(params.get("path", "."))
        if not os.path.isdir(path):
            return {"error": f"Not a directory: {path}"}
        entries = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            entries.append({
                "name": name,
                "type": "dir" if os.path.isdir(full) else "file",
                "size": os.path.getsize(full) if os.path.isfile(full) else None,
            })
        return entries

    def _action_read(self, params):
        path = self._safe(params.get("path", ""))
        if not os.path.isfile(path):
            return {"error": f"Not a file: {path}"}
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(200_000)  # bounded read
        return {"path": params.get("path"), "content": content}

    def _action_exists(self, params):
        path = self._safe(params.get("path", ""))
        return {"exists": os.path.exists(path), "path": params.get("path")}

    def _action_tree(self, params):
        path = self._safe(params.get("path", "."))
        max_depth = int(params.get("depth", 2))
        out = []

        def walk(cur, depth):
            if depth > max_depth:
                return
            for name in sorted(os.listdir(cur)):
                full = os.path.join(cur, name)
                rel = os.path.relpath(full, ROOT)
                out.append(rel)
                if os.path.isdir(full):
                    walk(full, depth + 1)

        walk(path, 0)
        return out[:200]

    def _action_stat(self, params):
        path = self._safe(params.get("path", ""))
        if not os.path.exists(path):
            return {"error": "Path not found"}
        st = os.stat(path)
        return {
            "path": params.get("path"),
            "size": st.st_size,
            "is_dir": os.path.isdir(path),
            "mtime": st.st_mtime,
        }
