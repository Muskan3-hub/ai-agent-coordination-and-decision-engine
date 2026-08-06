"""
GitHub Tool.

Refactored (Task 5) so that ALL GitHub operations flow through the MCP
layer (mcp/) instead of talking to the GitHub API directly. The public
API (`execute` / `get_repo`) is unchanged, so the rest of the
application keeps working without any breaking changes.
"""

from mcp import MCPManager
from tools.base_tool import BaseTool

# Legacy action names -> MCP action names. Kept as an explicit map so
# the GitHubTool API stays stable while the MCP server evolves.
ACTION_MAP = {
    "repo_info": "repo_info",
    "branches": "branches",
    "commits": "commits",
    "tree": "tree",
    "browse_file": "browse_file",
    "stats": "stats",
    "issues": "issues",
    "pull_requests": "pull_requests",
    "recent_updates": "recent_updates",
}


class GitHubTool(BaseTool):

    def __init__(self, mcp=None):
        # Allow injecting a pre-built MCPManager (or a mock in tests).
        self.mcp = mcp or MCPManager()

    def execute(self, input_data):
        """
        Run a GitHub action through the MCP layer.

        input_data example:
            {"action": "repo_info", "owner": "tensorflow", "repo": "tensorflow"}
            {"action": "branches", "owner": "...", "repo": "..."}
        """
        action = input_data.get("action")
        mcp_action = ACTION_MAP.get(action)

        if mcp_action is None:
            return f"Unsupported GitHub action: {action}"

        params = {
            key: value
            for key, value in input_data.items()
            if key not in ("action",)
        }

        result = self.mcp.call("github", mcp_action, params)

        if not result.get("success"):
            return result.get("error", "GitHub request failed")

        return result.get("data")

    def get_repo(self, owner, repo):
        """Legacy convenience method - returns the classic info dict."""
        result = self.execute({
            "action": "repo_info",
            "owner": owner,
            "repo": repo,
        })

        if not isinstance(result, dict):
            return result

        return {
            "name": result.get("name"),
            "stars": result.get("stars", 0),
            "forks": result.get("forks", 0),
            "language": result.get("language"),
        }
