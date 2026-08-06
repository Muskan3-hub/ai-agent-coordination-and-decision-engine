"""Knowledge MCP server: RAG over the project (Task 5).

Wraps the stdlib-only rag.KnowledgeIndex so agents, the coordinator and
the UI can semantically search the codebase - locate functions/classes,
explain architecture, find dependencies and relevant snippets.
"""
import os

from mcp.base import MCPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_index = None


class KnowledgeMCPServer(MCPServer):
    name = "knowledge"

    actions = {
        "index": "Index the project (idempotent, cached)",
        "search": "Semantic search over the codebase",
        "locate": "Locate a function or class definition",
        "context": "Retrieve context chunks for an LLM prompt",
        "status": "Index statistics",
    }

    def _get_index(self):
        global _index
        if _index is None:
            from rag import index_project
            _index = index_project(ROOT)
        return _index

    def _action_index(self, params):
        idx = self._get_index()
        return {"indexed_chunks": len(idx.docs)}

    def _action_status(self, params):
        idx = self._get_index()
        files = sorted({d["file"] for d in idx.docs})
        return {"chunks": len(idx.docs), "files": len(files), "sample_files": files[:10]}

    def _action_search(self, params):
        query = params.get("query", "")
        if not query:
            return {"error": "query is required"}
        return self._get_index().search(query, top_k=int(params.get("top_k", 5)))

    def _action_locate(self, params):
        name = params.get("name", "")
        if not name:
            return {"error": "name is required"}
        return self._get_index().locate(name, kind=params.get("kind"))

    def _action_context(self, params):
        query = params.get("query", "")
        if not query:
            return {"error": "query is required"}
        return {
            "context": self._get_index().context_for(
                query, top_k=int(params.get("top_k", 3))
            )
        }
