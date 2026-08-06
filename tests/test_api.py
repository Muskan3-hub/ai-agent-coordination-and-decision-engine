"""Tests for the REST API layer (auth, health, dashboard, routing)."""
import database
from api import APIServer
from auth import AuthService


def _make_server():
    db = database.init_db(":memory:")
    server = APIServer()
    server.db = db
    server.auth = AuthService(db)
    server.auth.ensure_default_admin()
    return server


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
