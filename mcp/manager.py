"""MCPManager: registry + dispatcher for MCP servers (auto-discovery)."""
import importlib
import inspect
import pkgutil

from mcp.base import MCPServer
from mcp.servers.github_server import GitHubMCPServer


class MCPManager:
    """Central registry + dispatcher for MCP servers.

    - `register(server)`   : add a new MCPServer to the pool
    - `call(name, action)` : route an action to the matching server
    - `list_servers()`     : describe every registered server
    - `discover()`         : auto-register every server module in mcp.servers

    Adding support for a new external service is a single `register`
    call - the rest of the application is untouched.
    """

    def __init__(self, servers=None, auto_discover=True):
        self._servers = {}
        if servers is not None:
            for server in servers:
                self.register(server)
        elif auto_discover:
            self.discover()
        else:
            self.register(GitHubMCPServer())

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def discover(self):
        """Auto-register every MCPServer subclass in mcp/servers/*.py."""
        import mcp.servers as servers_pkg

        for modinfo in pkgutil.iter_modules(servers_pkg.__path__):
            if modinfo.name.endswith("_server"):
                module = importlib.import_module(
                    f"mcp.servers.{modinfo.name}"
                )
                for _, cls in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(cls, MCPServer)
                        and cls is not MCPServer
                        and getattr(cls, "name", None)
                    ):
                        self.register(cls())

    def register(self, server):
        if not isinstance(server, MCPServer):
            raise TypeError(f"Expected an MCPServer, got {type(server).__name__}")
        self._servers[server.name] = server
        return server

    def get(self, name):
        """Return the server registered under `name` or None."""
        return self._servers.get(name)

    def call(self, server_name, action, params=None):
        """Dispatch `action` to the registered server `server_name`.

        Always returns a result dict with a `success` flag so callers
        never have to handle raw exceptions:
            {"success": True,  "data": <result>}
            {"success": False, "error": "..."}
        """
        server = self._servers.get(server_name)
        if server is None:
            return {
                "success": False,
                "error": f"Unknown MCP server: {server_name}",
            }

        if action not in server.actions:
            return {
                "success": False,
                "error": (
                    f"Unsupported action '{action}' for MCP server "
                    f"'{server_name}'. Available: {server.list_actions()}"
                ),
            }

        try:
            data = server.handle(action, params or {})
        except Exception as exc:  # network / API errors
            return {"success": False, "error": str(exc)}

        # Servers return {"error": ...} dicts for API-level failures.
        if isinstance(data, dict) and "error" in data:
            return {"success": False, "error": data["error"]}

        return {"success": True, "data": data}

    def list_servers(self):
        """Return a dict {server_name: describe()} for all servers."""
        return {
            name: server.describe()
            for name, server in self._servers.items()
        }
