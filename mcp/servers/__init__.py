"""
Concrete MCP server implementations.

Adding a new integration (Filesystem, Git, Database, ...) means adding
a new module in this folder and registering it in MCPManager.
"""

from mcp.servers.github_server import GitHubMCPServer

__all__ = ["GitHubMCPServer"]
