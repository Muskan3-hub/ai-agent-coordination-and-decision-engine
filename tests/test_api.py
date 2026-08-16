"""Tests for the REST API layer (auth, health, dashboard, routing)."""
import database
from api import APIServer
from auth import AuthService


class FakeCoordinator:
    """Stubbed coordinator - no live LLM calls in tests."""

    def handle_task(self, task):
        return {
            "response": f"handled: {task}",
            "agent": "Test Workflow",
            "workflow": {"planner": "p", "coding": "c", "documentation": "d"},
        }


def _make_server():
    db = database.init_db(":memory:")
    server = APIServer()
    server.db = db
    server.auth = AuthService(db)
    # Explicit password: the app's .env may set ADMIN_PASSWORD, which
    # would otherwise make the default admin differ from the test
    # credentials (and break tests depending on import order).
    server.auth.ensure_default_admin(password="admin123")
    return server


def _login(server):
    _, payload = server._handle_request("POST", "/api/login", {
        "username": "admin", "password": "admin123",
    })
    return payload["token"]


def test_health_endpoint():
    server = _make_server()
    status, payload = server._handle_request("GET", "/api/health", {})
    assert status == 200
    assert payload["status"] == "ok"


def test_login_endpoint():
    server = _make_server()
    status, payload = server._handle_request("POST", "/api/login", {
        "username": "admin", "password": "admin123",
    })
    assert status == 200
    assert payload["success"] is True
    assert "token" in payload


def test_login_rejects_bad_credentials():
    server = _make_server()
    status, payload = server._handle_request("POST", "/api/login", {
        "username": "admin", "password": "wrong",
    })
    assert status == 401


def test_dashboard_requires_auth():
    server = _make_server()
    status, _ = server._handle_request("GET", "/api/dashboard", {"token": "bad"})
    assert status == 401


def test_dashboard_with_token():
    server = _make_server()
    _, login = server._handle_request("POST", "/api/login", {
        "username": "admin", "password": "admin123",
    })
    status, payload = server._handle_request(
        "GET", "/api/dashboard", {"token": login["token"]}
    )
    assert status == 200
    assert "total_executions" in payload["data"]


def test_unknown_route():
    server = _make_server()
    status, payload = server._handle_request("GET", "/api/nope", {})
    assert status == 404
    assert payload["success"] is False


# ======================================================================
# Milestone 4 - workflow execution / status / history / monitoring
# ======================================================================


def test_workflow_execute_requires_auth():
    server = _make_server()
    status, payload = server._handle_request(
        "POST", "/api/workflows/execute", {"message": "x", "token": "bad"}
    )
    assert status == 401


def test_workflow_execute_and_status_and_history():
    server = _make_server()
    server.get_coordinator = lambda: FakeCoordinator()
    token = _login(server)

    status, payload = server._handle_request(
        "POST", "/api/workflows/execute",
        {"message": "Build a calculator app", "type": "build", "token": token},
    )
    assert status == 200
    assert payload["success"] is True
    assert payload["status"] == "completed"
    assert payload["workflow_id"] is not None
    assert payload["agent"] == "Test Workflow"

    # Status by id.
    status2, payload2 = server._handle_request(
        "GET", f"/api/workflows/{payload['workflow_id']}", {"token": token}
    )
    assert status2 == 200
    assert payload2["workflow"]["id"] == payload["workflow_id"]
    assert payload2["workflow"]["status"] == "completed"

    # History list.
    status3, payload3 = server._handle_request(
        "GET", "/api/workflows", {"token": token}
    )
    assert status3 == 200
    assert len(payload3["workflows"]) >= 1


def test_workflow_status_not_found():
    server = _make_server()
    token = _login(server)
    status, payload = server._handle_request(
        "GET", "/api/workflows/99999", {"token": token}
    )
    assert status == 404
    assert payload["success"] is False


def test_workflow_directive_mapping():
    """Explicit workflow types produce the matching chain directive."""
    server = _make_server()
    assert "Build an application: calc" == server._workflow_directive(
        "build", "calc"
    )
    assert "Review this project: repo" == server._workflow_directive(
        "review_project", "repo"
    )
    assert "calc" == server._workflow_directive("auto", "calc")
    assert "calc" == server._workflow_directive("bogus", "calc")


def test_agent_logs_endpoint():
    server = _make_server()
    server.db.log_agent("TestAgent", action="run", status="success", detail="x")
    server.db.log_execution(1, "TestAgent", "success", 42)
    token = _login(server)
    status, payload = server._handle_request(
        "GET", "/api/agents/logs", {"token": token}
    )
    assert status == 200
    assert payload["success"] is True
    assert any(log["agent"] == "TestAgent" for log in payload["logs"])
    assert any(e["agent"] == "TestAgent" for e in payload["executions"])


def test_system_health_includes_metrics():
    from monitoring.metrics import get_metrics

    server = _make_server()
    get_metrics().record_request(15)
    status, payload = server._handle_request("GET", "/api/system/health", {})
    assert status == 200
    assert payload["status"] == "ok"
    assert payload["metrics"]["requests"] >= 1
    assert "memory" in payload["metrics"]
    assert payload["database"]["ok"] is True
    assert "by_status" in payload["workflows"]


def test_metrics_module_records():
    from monitoring.metrics import Metrics

    m = Metrics()
    m.record_request(10)
    m.record_request(20, ok=False)
    m.record_llm()
    m.record_tool("FileTool")
    m.record_agent("Coding Agent", 1500)
    m.record_workflow(ok=True)
    snap = m.snapshot()
    assert snap["requests"] == 2
    assert snap["errors"] == 1
    assert snap["llm_calls"] == 1
    assert snap["tool_calls"] == 1
    assert snap["agent_usage"][0]["agent"] == "Coding Agent"
    assert snap["workflows_started"] == 1
    assert snap["memory"]["rss_mb"] is not None
