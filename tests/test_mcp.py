"""Tests for the MCP (Model Context Protocol) layer (Task 4/5)."""

import pytest

from mcp import MCPManager, MCPServer, GitHubMCPServer
from tools.github_tool import GitHubTool


class FakeServer(MCPServer):
    """Minimal fake server to validate the registry/dispatch contract."""

    name = "fake"
    actions = {
        "ping": "returns pong",
        "echo": "echoes params",
    }

    def handle(self, action, params=None):
        params = params or {}
        if action == "ping":
            return "pong"
        if action == "echo":
            return params
        raise ValueError(f"unsupported: {action}")


# ----------------------------------------------------------------------
# Registry / dispatch
# ----------------------------------------------------------------------
def test_manager_registers_and_lists_servers():
    manager = MCPManager(servers=[FakeServer()])
    servers = manager.list_servers()
    assert "fake" in servers
    assert servers["fake"]["name"] == "fake"
    assert set(servers["fake"]["actions"].keys()) == {"ping", "echo"}


def test_manager_routes_actions():
    manager = MCPManager(servers=[FakeServer()])
    assert manager.call("fake", "ping") == {"success": True, "data": "pong"}
    assert manager.call("fake", "echo", {"x": 1}) == {
        "success": True,
        "data": {"x": 1},
    }


def test_manager_unknown_server():
    manager = MCPManager(servers=[FakeServer()])
    result = manager.call("nope", "ping")
    assert result["success"] is False
    assert "Unknown MCP server" in result["error"]


def test_manager_unsupported_action():
    manager = MCPManager(servers=[FakeServer()])
    result = manager.call("fake", "bogus")
    assert result["success"] is False
    assert "bogus" in result["error"]


def test_manager_catches_handler_exceptions():
    class ExplodingServer(FakeServer):
        name = "explode"

        def handle(self, action, params=None):
            raise RuntimeError("boom")

    manager = MCPManager(servers=[ExplodingServer()])
    result = manager.call("explode", "ping")
    assert result["success"] is False
    assert "boom" in result["error"]


# ----------------------------------------------------------------------
# GitHub MCP server (hermetic - fake HTTP layer)
# ----------------------------------------------------------------------
class FakeGitHubResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    # Non-200 responses read .text to build the error message.
    @property
    def text(self):
        return str(self._payload)


@pytest.fixture
def fake_github(monkeypatch):
    """Routes requests.get inside the GitHub server to canned responses."""

    def factory(path_to_response):
        # Match the MOST SPECIFIC (longest) URL SUFFIX first, so
        # ".../repos/a/b/commits" matches the commits stub and not the
        # generic ".../repos/a/b" repo stub.
        ordered = sorted(
            path_to_response.items(), key=lambda kv: len(kv[0]), reverse=True
        )

        def fake_get(url, headers=None, params=None, timeout=None):
            for key, response in ordered:
                if url.rstrip("/").endswith(key):
                    return response
            return FakeGitHubResponse(404, {"message": "Not Found"})

        monkeypatch.setattr(
            "mcp.servers.github_server.requests.get",
            fake_get,
        )
        server = GitHubMCPServer()
        # Isolate tests from any real GITHUB_TOKEN in .env so
        # rate-limit/auth assertions are deterministic.
        server.token = ""
        return server

    return factory


def test_github_repo_info(fake_github):
    server = fake_github({
        "/repos/a/b": FakeGitHubResponse(200, {
            "name": "b",
            "full_name": "a/b",
            "stargazers_count": 42,
            "forks_count": 7,
            "language": "Python",
            "open_issues_count": 3,
            "default_branch": "main",
        }),
    })
    info = server.handle("repo_info", {"owner": "a", "repo": "b"})
    assert info["stars"] == 42
    assert info["forks"] == 7
    assert info["language"] == "Python"


def test_github_branches(fake_github):
    server = fake_github({
        "/branches": FakeGitHubResponse(200, [
            {"name": "main", "protected": True},
            {"name": "dev", "protected": False},
        ]),
    })
    branches = server.handle("branches", {"owner": "a", "repo": "b"})
    assert branches == [
        {"name": "main", "protected": True},
        {"name": "dev", "protected": False},
    ]


def test_github_commits(fake_github):
    server = fake_github({
        "/commits": FakeGitHubResponse(200, [
            {
                "sha": "abc123def456",
                "commit": {
                    "message": "fix bug\n\nmore detail",
                    "author": {"name": "Alice", "date": "2026-01-01"},
                },
            },
        ]),
    })
    commits = server.handle("commits", {"owner": "a", "repo": "b"})
    assert commits[0]["sha"] == "abc123d"
    assert commits[0]["message"] == "fix bug"
    assert commits[0]["author"] == "Alice"


def test_github_tree(fake_github):
    server = fake_github({
        "/git/trees/main": FakeGitHubResponse(200, {
            "tree": [
                {"path": "app.py", "type": "blob"},
                {"path": "src", "type": "tree"},
            ],
        }),
    })
    tree = server.handle("tree", {"owner": "a", "repo": "b", "branch": "main"})
    assert tree == [
        {"path": "app.py", "type": "blob"},
        {"path": "src", "type": "tree"},
    ]


def test_github_browse_file(fake_github):
    import base64
    content = base64.b64encode(b"print('hello')").decode()
    server = fake_github({
        "/contents/app.py": FakeGitHubResponse(200, {
            "content": content,
            "size": 15,
        }),
    })
    result = server.handle("browse_file", {"owner": "a", "repo": "b", "path": "app.py"})
    assert result["type"] == "file"
    assert result["content"] == "print('hello')"


def test_github_stats(fake_github):
    server = fake_github({
        "/languages": FakeGitHubResponse(200, {"Python": 100, "HTML": 20}),
        "/repos/a/b": FakeGitHubResponse(200, {
            "full_name": "a/b",
            "stargazers_count": 5,
            "forks_count": 2,
            "open_issues_count": 1,
            "default_branch": "main",
        }),
    })
    stats = server.handle("stats", {"owner": "a", "repo": "b"})
    assert stats["stars"] == 5
    assert stats["languages"] == {"Python": 100, "HTML": 20}


def test_github_issues(fake_github):
    server = fake_github({
        "/issues": FakeGitHubResponse(200, [
            {"number": 1, "title": "bug", "state": "open", "labels": [{"name": "bug"}]},
        ]),
    })
    issues = server.handle("issues", {"owner": "a", "repo": "b"})
    assert issues[0]["title"] == "bug"
    assert issues[0]["labels"] == ["bug"]


def test_github_pull_requests(fake_github):
    server = fake_github({
        "/pulls": FakeGitHubResponse(200, [
            {"number": 10, "title": "feat", "state": "open", "user": {"login": "bob"}},
        ]),
    })
    prs = server.handle("pull_requests", {"owner": "a", "repo": "b"})
    assert prs[0]["author"] == "bob"


def test_github_recent_updates(fake_github):
    server = fake_github({
        "/repos/a/b": FakeGitHubResponse(200, {
            "full_name": "a/b",
            "pushed_at": "2026-02-02T00:00:00Z",
            "default_branch": "main",
        }),
        "/commits": FakeGitHubResponse(200, [
            {
                "sha": "1234567890",
                "commit": {
                    "message": "update",
                    "author": {"name": "Eve", "date": "2026-02-02"},
                },
            },
        ]),
    })
    updates = server.handle("recent_updates", {"owner": "a", "repo": "b"})
    assert updates["pushed_at"] == "2026-02-02T00:00:00Z"
    assert updates["recent_commits"][0]["message"] == "update"


def test_github_server_error_handling(fake_github):
    server = fake_github({})  # everything 404s
    result = server.handle("repo_info", {"owner": "nope", "repo": "nope"})
    assert "error" in result


# ----------------------------------------------------------------------
# GitHubTool still works through MCP (Task 5 - no breaking changes)
# ----------------------------------------------------------------------
def test_github_tool_delegates_to_mcp_manager(monkeypatch):
    server = GitHubMCPServer()

    def fake_get(url, headers=None, params=None, timeout=None):
        return FakeGitHubResponse(200, {
            "name": "b",
            "full_name": "a/b",
            "stargazers_count": 3,
            "forks_count": 1,
            "language": "Go",
        })

    monkeypatch.setattr("mcp.servers.github_server.requests.get", fake_get)

    tool = GitHubTool(mcp=MCPManager(servers=[server]))
    info = tool.get_repo("a", "b")
    assert info == {"name": "b", "stars": 3, "forks": 1, "language": "Go"}


def test_github_rate_limit(fake_github):
    server = fake_github({
        "/rate_limit": FakeGitHubResponse(200, {
            "resources": {
                "core": {
                    "limit": 60,
                    "remaining": 42,
                    "used": 18,
                    "reset": 1754294400,
                },
            },
        }),
    })
    result = server.handle("rate_limit", {})
    assert result["authenticated"] is False
    assert result["limit"] == 60
    assert result["remaining"] == 42
    assert result["used"] == 18
    assert result["reset"] == 1754294400
    assert "rate_limit" in GitHubMCPServer.actions


def test_github_rate_limit_rejected_token_falls_back(monkeypatch):
    """
    A configured but rejected token (401) must not poison the readout:
    the server retries anonymously and reports token_valid=False so the
    UI can warn the user while still showing real anonymous quota.
    """
    anonymous_payload = {
        "resources": {
            "core": {"limit": 60, "remaining": 55, "used": 5, "reset": 0}
        },
    }

    def fake_get(url, headers=None, params=None, timeout=None):
        # Requests that carry the (placeholder) token get 401.
        if headers and headers.get("Authorization"):
            return FakeGitHubResponse(401, {"message": "Bad credentials"})
        return FakeGitHubResponse(200, anonymous_payload)

    monkeypatch.setattr(
        "mcp.servers.github_server.requests.get",
        fake_get,
    )
    server = GitHubMCPServer(token="ghp_PLACEHOLDER")

    result = server.handle("rate_limit", {})
    assert result["authenticated"] is False
    assert result["token_valid"] is False
    assert result["limit"] == 60
    assert result["remaining"] == 55
