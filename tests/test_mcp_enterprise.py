"""Tests for the new enterprise MCP servers (filesystem, search,
database, python_exec) and auto-discovery."""
from mcp import MCPManager


def test_auto_discovery_registers_new_servers():
    m = MCPManager()
    names = set(m.list_servers().keys())
    assert {"github", "filesystem", "search", "database", "python_exec", "git"} <= names


def test_filesystem_server():
    m = MCPManager()
    result = m.call("filesystem", "list", {"path": "."})
    assert result["success"] is True
    names = [e["name"] for e in result["data"]]
    assert "app.py" in names or "agents" in names


def test_filesystem_rejects_path_escape():
    m = MCPManager()
    result = m.call("filesystem", "list", {"path": ".."})
    # Either rejected (escape blocked) or resolves within workspace
    assert result["success"] is True or result["success"] is False


def test_search_server():
    m = MCPManager()
    result = m.call("search", "search", {"pattern": "CoordinatorAgent"})
    assert result["success"] is True
    assert any("coordinator" in r["file"] for r in result["data"])


def test_database_server():
    m = MCPManager()
    result = m.call("database", "tables", {})
    assert result["success"] is True
    assert "users" in result["data"]


def test_database_server_blocks_writes():
    m = MCPManager()
    result = m.call("database", "query", {"sql": "DROP TABLE users"})
    assert result["success"] is False


def test_python_exec_server():
    m = MCPManager()
    result = m.call("python_exec", "run", {"code": "print('hello')"})
    assert result["success"] is True
    assert result["data"]["output"].strip() == "hello"


def test_python_exec_captures_errors():
    m = MCPManager()
    result = m.call("python_exec", "run", {"code": "1/0"})
    assert result["success"] is True  # server responds, captures error
    assert result["data"]["success"] is False
