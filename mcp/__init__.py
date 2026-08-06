"""
MCP (Model Context Protocol) layer.

A modular layer that lets external services (GitHub, and in the future
Filesystem, Git, Database, ...) expose capabilities as "MCP servers".
The rest of the application talks to this layer through MCPManager
instead of talking to the services directly.

    mcp/
        __init__.py          -> public API (MCPManager, GitHubMCPServer)
        base.py              -> MCPServer base contract
        manager.py           -> registry + dispatcher
        servers/
            github_server.py -> GitHub MCP server
"""

from mcp.base import MCPServer
from mcp.manager import MCPManager
from mcp.servers.github_server import GitHubMCPServer

__all__ = ["MCPServer", "MCPManager", "GitHubMCPServer"]
