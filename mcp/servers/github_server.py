"""GitHub MCP server.

Exposes GitHub repository capabilities through the MCP layer. This is
the ONLY place in the codebase that talks to the GitHub REST API
directly - everything else (GitHubTool, Coordinator, UI) goes through
MCPManager.call("github", action, params).
"""

import base64
import os

import requests

from mcp.base import MCPServer

GITHUB_API_URL = "https://api.github.com"
DEFAULT_TIMEOUT = 15


class GitHubMCPServer(MCPServer):
    """MCP server that provides GitHub repository data and operations."""

    name = "github"

    actions = {
        "repo_info": "Basic repository information (stars, forks, language)",
        "branches": "List repository branches",
        "commits": "List recent commit history",
        "tree": "List repository file tree",
        "browse_file": "Read a file from the repository",
        "stats": "Repository statistics (languages, sizes)",
        "issues": "List open issues",
        "pull_requests": "List open pull requests",
        "recent_updates": "Latest repository activity (commits + pushes)",
        "rate_limit": "Check GitHub API quota (token / anonymous)",
        "compare_commits": "Compare two branches/refs",
        "contributors": "Top contributors",
        "releases": "Latest releases",
        "code_frequency": "Additions/deletions per week",
        "security_alerts": "Vulnerability alert status",
    }

    def __init__(self, token=None):
        # Optional personal access token (used for higher rate limits).
        self.token = token or os.getenv("GITHUB_TOKEN", "")

    # =====================================================================
    # Dispatch
    # =====================================================================
    def handle(self, action, params=None):
        """Execute a single GitHub action (params: owner, repo, ...)."""
        params = params or {}
        handler = getattr(self, f"_action_{action}", None)
        if handler is None:
            raise ValueError(f"Unsupported GitHub MCP action: {action}")
        return handler(params)

    # =====================================================================
    # HTTP helpers
    # =====================================================================
    def _headers(self, use_token=True):
        headers = {"Accept": "application/vnd.github+json"}
        if self.token and use_token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(self, path, params=None, use_token=True):
        """GET a GitHub API endpoint and return parsed JSON."""
        url = f"{GITHUB_API_URL}{path}"
        response = requests.get(
            url,
            headers=self._headers(use_token=use_token),
            params=params,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code == 404:
            return {"error": "Repository or resource not found"}
        if response.status_code != 200:
            return {
                "error": f"GitHub API error {response.status_code}: "
                f"{response.text[:300]}"
            }
        return response.json()

    @staticmethod
    def _repo_params(params):
        """Validate and normalize owner/repo params."""
        owner = (params.get("owner") or "").strip()
        repo = (params.get("repo") or "").strip().rstrip("/")
        if not owner or not repo:
            raise ValueError("Both 'owner' and 'repo' are required.")
        return owner, repo

    @staticmethod
    def _fmt_repo(owner, repo):
        return f"{owner}/{repo}"

    # =====================================================================
    # Actions
    # =====================================================================
    def _action_repo_info(self, params):
        owner, repo = self._repo_params(params)
        data = self._get(f"/repos/{self._fmt_repo(owner, repo)}")
        if "error" in data:
            return data
        return {
            "name": data.get("name"),
            "full_name": data.get("full_name"),
            "description": data.get("description"),
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "language": data.get("language"),
            "open_issues": data.get("open_issues_count", 0),
            "default_branch": data.get("default_branch"),
            "html_url": data.get("html_url"),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "pushed_at": data.get("pushed_at"),
        }

    def _action_branches(self, params):
        owner, repo = self._repo_params(params)
        data = self._get(
            f"/repos/{self._fmt_repo(owner, repo)}/branches",
            {"per_page": params.get("per_page", 50)},
        )
        if "error" in data:
            return data
        return [
            {"name": branch.get("name"), "protected": branch.get("protected", False)}
            for branch in data
        ]

    def _action_commits(self, params):
        owner, repo = self._repo_params(params)
        data = self._get(
            f"/repos/{self._fmt_repo(owner, repo)}/commits",
            {
                "per_page": params.get("per_page", 10),
                "sha": params.get("branch"),
            },
        )
        if "error" in data:
            return data
        return [
            {
                "sha": commit.get("sha", "")[:7],
                "message": (
                    commit.get("commit", {}).get("message", "").splitlines()
                    or [""]
                )[0],
                "author": commit.get("commit", {}).get("author", {}).get("name"),
                "date": commit.get("commit", {}).get("author", {}).get("date"),
            }
            for commit in data
        ]

    def _action_tree(self, params):
        owner, repo = self._repo_params(params)
        branch = params.get("branch") or "main"
        data = self._get(
            f"/repos/{self._fmt_repo(owner, repo)}/git/trees/{branch}",
            {"recursive": "1"},
        )
        if "error" in data:
            return data
        tree = data.get("tree", [])
        return [
            {"path": item.get("path"), "type": item.get("type")}
            for item in tree
        ]

    def _action_browse_file(self, params):
        owner, repo = self._repo_params(params)
        path = (params.get("path") or "").strip().lstrip("/")
        if not path:
            raise ValueError("'path' is required for browse_file.")
        data = self._get(f"/repos/{self._fmt_repo(owner, repo)}/contents/{path}")
        if "error" in data:
            return data

        # A directory listing returns a JSON array.
        if isinstance(data, list):
            return {
                "type": "dir",
                "path": path,
                "entries": [
                    {"name": item.get("name"), "type": item.get("type")}
                    for item in data
                ],
            }

        # A file returns an object with base64-encoded content.
        try:
            content = base64.b64decode(data.get("content", "")).decode("utf-8")
        except Exception:
            content = data.get("content", "")
        return {
            "type": "file",
            "path": path,
            "size": data.get("size"),
            "content": content,
        }

    def _action_stats(self, params):
        owner, repo = self._repo_params(params)
        languages = self._get(f"/repos/{self._fmt_repo(owner, repo)}/languages")
        info = self._get(f"/repos/{self._fmt_repo(owner, repo)}")
        if "error" in languages:
            return languages
        if "error" in info:
            return info
        return {
            "full_name": info.get("full_name"),
            "languages": languages if isinstance(languages, dict) else {},
            "size_kb": info.get("size"),
            "stars": info.get("stargazers_count", 0),
            "forks": info.get("forks_count", 0),
            "open_issues": info.get("open_issues_count", 0),
            "default_branch": info.get("default_branch"),
        }

    def _action_issues(self, params):
        owner, repo = self._repo_params(params)
        data = self._get(
            f"/repos/{self._fmt_repo(owner, repo)}/issues",
            {"state": params.get("state", "open"), "per_page": params.get("per_page", 10)},
        )
        if "error" in data:
            return data
        return [
            {
                "number": issue.get("number"),
                "title": issue.get("title"),
                "state": issue.get("state"),
                "labels": [label.get("name") for label in issue.get("labels", [])],
                "created_at": issue.get("created_at"),
            }
            for issue in data
        ]

    def _action_pull_requests(self, params):
        owner, repo = self._repo_params(params)
        data = self._get(
            f"/repos/{self._fmt_repo(owner, repo)}/pulls",
            {"state": params.get("state", "open"), "per_page": params.get("per_page", 10)},
        )
        if "error" in data:
            return data
        return [
            {
                "number": pr.get("number"),
                "title": pr.get("title"),
                "state": pr.get("state"),
                "author": (pr.get("user") or {}).get("login"),
                "created_at": pr.get("created_at"),
            }
            for pr in data
        ]

    def _action_recent_updates(self, params):
        owner, repo = self._repo_params(params)
        info = self._get(f"/repos/{self._fmt_repo(owner, repo)}")
        if "error" in info:
            return info
        commits = self._action_commits({**params, "per_page": params.get("per_page", 5)})
        return {
            "pushed_at": info.get("pushed_at"),
            "default_branch": info.get("default_branch"),
            "recent_commits": commits if isinstance(commits, list) else [],
        }

    # =====================================================================
    # Advanced actions (Task 8 of the enterprise upgrade)
    # =====================================================================
    def _action_compare_commits(self, params):
        owner, repo = self._repo_params(params)
        base = params.get("base", "main")
        head = params.get("head", "main")
        data = self._get(
            f"/repos/{self._fmt_repo(owner, repo)}/compare/{base}...{head}"
        )
        if "error" in data:
            return data
        return {
            "base": base,
            "head": head,
            "ahead_by": data.get("ahead_by"),
            "behind_by": data.get("behind_by"),
            "total_commits": data.get("total_commits"),
            "files": [
                {"filename": f.get("filename"), "status": f.get("status")}
                for f in (data.get("files") or [])
            ],
        }

    def _action_contributors(self, params):
        owner, repo = self._repo_params(params)
        data = self._get(
            f"/repos/{self._fmt_repo(owner, repo)}/contributors",
            {"per_page": params.get("per_page", 10)},
        )
        if "error" in data:
            return data
        return [
            {"login": c.get("login"), "contributions": c.get("contributions")}
            for c in data
        ]

    def _action_releases(self, params):
        owner, repo = self._repo_params(params)
        data = self._get(
            f"/repos/{self._fmt_repo(owner, repo)}/releases",
            {"per_page": params.get("per_page", 5)},
        )
        if "error" in data:
            return data
        return [
            {
                "tag": r.get("tag_name"),
                "name": r.get("name"),
                "published_at": r.get("published_at"),
                "author": (r.get("author") or {}).get("login"),
            }
            for r in data
        ]

    def _action_code_frequency(self, params):
        owner, repo = self._repo_params(params)
        data = self._get(
            f"/repos/{self._fmt_repo(owner, repo)}/stats/code_frequency"
        )
        if "error" in data:
            return data
        return [
            {"week": row[0], "additions": row[1], "deletions": row[2]}
            for row in data
        ]

    def _action_security_alerts(self, params):
        owner, repo = self._repo_params(params)
        # The vulnerability-alerts endpoint requires admin permissions and
        # is often 404/204 - surface a friendly message instead of a hard
        # error so the UI can show "not available" gracefully.
        data = self._get(
            f"/repos/{self._fmt_repo(owner, repo)}/vulnerability-alerts",
        )
        if isinstance(data, dict) and "error" not in data:
            return {"available": True, "status": data}
        return {
            "available": False,
            "message": "Security alerts require admin access or are not enabled for this repo.",
        }


    def _action_rate_limit(self, params):
        """
        GitHub API quota readout.

        GET /rate_limit does NOT consume quota itself, so it is safe to
        call on every UI render. Returns the core-resource limits and
        whether a token is configured.

        When a token IS configured but GitHub rejects it (401 - expired,
        revoked or placeholder), we retry anonymously so the caller still
        gets real quota numbers, and set ``token_valid: False`` so the
        UI can warn the user instead of silently showing an error.
        """
        data = self._get("/rate_limit")
        if "error" in data and self.token:
            # Token present but rejected -> fall back to anonymous quota.
            anonymous = self._get("/rate_limit", use_token=False)
            if "error" not in anonymous:
                core = anonymous.get("resources", {}).get("core", {})
                return {
                    "authenticated": False,
                    "token_valid": False,
                    "token_error": data["error"],
                    "limit": core.get("limit"),
                    "remaining": core.get("remaining"),
                    "used": core.get("used"),
                    "reset": core.get("reset"),  # unix timestamp
                }
            return data
        if "error" in data:
            return data
        core = data.get("resources", {}).get("core", {})
        return {
            "authenticated": bool(self.token),
            "token_valid": True,
            "limit": core.get("limit"),
            "remaining": core.get("remaining"),
            "used": core.get("used"),
            "reset": core.get("reset"),  # unix timestamp
        }
