from abc import ABC


class MCPServer(ABC):
    """
    Base contract for every MCP server.

    A server exposes a set of *actions* (capabilities). Each action is
    implemented as a method `_action_<name>` on the server and is
    dispatched through `handle(action, params)`.

    To add a new MCP server (Filesystem, Git, Database, ...):
        1. Subclass MCPServer
        2. Implement `_action_<name>` methods (or override `handle`)
        3. Register it in MCPManager
    """

    #: unique server name used for routing ("github", "filesystem", ...)
    name = "base"

    #: human-readable descriptions for every supported action
    #: {action_name: "what this action does"}
    actions = {}

    def handle(self, action, params=None):
        """
        Execute a single action on this server.

        Default dispatch: routes to the `_action_<name>` method.
        Servers with custom needs (e.g. GitHub) may override `handle`.

        Returns:
            The action result (dict/list/str).
        """
        params = params or {}
        handler = getattr(self, f"_action_{action}", None)
        if handler is None:
            raise ValueError(f"Unsupported action: {action}")
        return handler(params)

    def list_actions(self):
        """Return the list of supported action names."""
        return list(self.actions.keys())

    def describe(self):
        """Return a dict describing the server (used by the UI/logs)."""
        return {
            "name": self.name,
            "actions": dict(self.actions),
        }
