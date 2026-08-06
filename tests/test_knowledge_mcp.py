"""Tests for the knowledge MCP server (RAG - Task 5)."""
from mcp import MCPManager


def test_knowledge_server_discovered():
    m = MCPManager()
    assert "knowledge" in m.list_servers()


def test_knowledge_locate():
    m = MCPManager()
    result = m.call("knowledge", "locate", {"name": "CoordinatorAgent", "kind": "class"})
    assert result["success"] is True
    assert result["data"], "should locate CoordinatorAgent"
    assert "coordinator" in result["data"][0]["file"].lower()


def test_knowledge_search():
    m = MCPManager()
    result = m.call("knowledge", "search", {"query": "handle_task coordinator", "top_k": 3})
    assert result["success"] is True


def test_knowledge_status():
    m = MCPManager()
    result = m.call("knowledge", "status", {})
    assert result["success"] is True
    assert result["data"]["chunks"] > 0
