"""Git MCP server: read-only git inspection via subprocess (Task 7)."""
import os
import subprocess

from mcp.base import MCPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class GitMCPServer(MCPServer):
    name = "git"

    actions = {
        "status": "git status (short)",
        "log": "Recent commit history",
        "branch": "Current branch",
        "diff": "Uncommitted changes (bounded)",
        "repo_root": "Detect the git root",
    }

    def _run(self, args, cwd=None):
        proc = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd or ROOT,
            timeout=20,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def _action_repo_root(self, params):
        code, out, err = self._run(["rev-parse", "--show-toplevel"])
        if code != 0:
            return {"error": "Not a git repository"}
        return {"root": out.strip()}

    def _action_status(self, params):
        code, out, err = self._run(["status", "--short"])
        if code != 0:
            return {"error": "Not a git repository"}
        return {"lines": out.splitlines()}

    def _action_log(self, params):
        limit = int(params.get("limit", 10))
        code, out, err = self._run(
            ["log", f"-{limit}", "--pretty=format:%h|%an|%s"]
        )
        if code != 0:
            return {"error": "Not a git repository"}
        entries = []
        for line in out.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                entries.append({"sha": parts[0], "author": parts[1], "message": parts[2]})
        return entries

    def _action_branch(self, params):
        code, out, err = self._run(["branch", "--show-current"])
        if code != 0:
            return {"error": "Not a git repository"}
        return {"branch": out.strip() or "detached"}

    def _action_diff(self, params):
        code, out, err = self._run(["diff", "--stat"])
        if code != 0:
            return {"error": "Not a git repository"}
        return {"diff_stat": out.strip() or "No changes"}
