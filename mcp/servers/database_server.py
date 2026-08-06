"""Database MCP server: read-only query access to the app database (Task 7)."""
from mcp.base import MCPServer
from database import get_db


class DatabaseMCPServer(MCPServer):
    name = "database"

    actions = {
        "tables": "List all database tables",
        "query": "Run a SELECT query (read-only, bounded)",
        "stats": "Dashboard aggregates",
    }

    def __init__(self, db=None):
        self.db = db or get_db()

    def _action_tables(self, params):
        rows = self.db._query(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [r["name"] for r in rows]

    def _action_query(self, params):
        sql = (params.get("sql") or "").strip()
        if not sql.lower().startswith("select"):
            return {"error": "Only SELECT queries are allowed"}
        try:
            rows = self.db._query(sql)
        except Exception as e:
            return {"error": str(e)}
        return {"count": len(rows), "rows": rows[:100]}

    def _action_stats(self, params):
        return self.db.dashboard_stats()
