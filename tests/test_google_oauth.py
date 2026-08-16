"""Tests for the Google OAuth helpers and OAuth-based auth flows."""
import pytest

from auth import AuthService
from auth.google_oauth import (
    GoogleAuthError,
    config_report,
    get_callback_port,
    get_redirect_uri,
    is_configured,
    sign_in_with_google,
    validate_config,
)
import database


def test_is_configured_false_by_default(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    assert is_configured() is False


def test_is_configured_true_when_keys_set(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    assert is_configured() is True


def test_is_configured_false_when_port_invalid(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_CALLBACK_PORT", "not-a-port")
    assert is_configured() is False


def test_sign_in_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    with pytest.raises(GoogleAuthError):
        sign_in_with_google(timeout=1)


def test_sign_in_error_message_includes_redirect_uri(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    with pytest.raises(GoogleAuthError) as excinfo:
        sign_in_with_google(timeout=1)
    assert "http://localhost:8765/oauth2callback" in str(excinfo.value)


def test_callback_port_default(monkeypatch):
    monkeypatch.delenv("GOOGLE_CALLBACK_PORT", raising=False)
    assert get_callback_port() == 8765


def test_callback_port_custom(monkeypatch):
    monkeypatch.setenv("GOOGLE_CALLBACK_PORT", "9000")
    assert get_callback_port() == 9000


def test_callback_port_invalid_value(monkeypatch):
    monkeypatch.setenv("GOOGLE_CALLBACK_PORT", "abc")
    assert get_callback_port() is None


def test_callback_port_out_of_range(monkeypatch):
    monkeypatch.setenv("GOOGLE_CALLBACK_PORT", "70000")
    assert get_callback_port() is None


def test_redirect_uri_uses_configured_port(monkeypatch):
    monkeypatch.setenv("GOOGLE_CALLBACK_PORT", "9000")
    assert get_redirect_uri() == "http://localhost:9000/oauth2callback"


def test_redirect_uri_default_port(monkeypatch):
    monkeypatch.delenv("GOOGLE_CALLBACK_PORT", raising=False)
    assert get_redirect_uri() == "http://localhost:8765/oauth2callback"


def test_validate_config_ok(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_CALLBACK_PORT", "8765")
    report = validate_config()
    assert report["enabled"] is True
    assert report["problems"] == []
    assert report["callback_port"] == 8765
    assert report["redirect_uri"] == "http://localhost:8765/oauth2callback"


def test_validate_config_reports_all_problems(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("GOOGLE_CALLBACK_PORT", "not-a-port")
    report = validate_config()
    assert report["enabled"] is False
    assert len(report["problems"]) == 3
    assert report["redirect_uri"] is None


def test_redirect_uri_mismatch_hint_includes_uri():
    from auth.google_oauth import _friendly_oauth_error

    msg = _friendly_oauth_error(
        "redirect_uri_mismatch", redirect_uri="http://localhost:9000/oauth2callback"
    )
    assert "http://localhost:9000/oauth2callback" in msg
    assert "Google Cloud Console" in msg


def test_unknown_oauth_error_falls_back_gracefully():
    from auth.google_oauth import _friendly_oauth_error

    msg = _friendly_oauth_error("some_weird_error")
    assert "some_weird_error" in msg
    assert "Please try again" in msg


def test_exchange_code_maps_http_400_to_friendly_message(monkeypatch):
    import json as _json
    from urllib.error import HTTPError

    from auth import google_oauth as go

    class FakeErrorBody:
        def read(self):
            return _json.dumps({"error": "invalid_grant"}).encode("utf-8")

    def fake_urlopen(req, timeout=30):
        raise HTTPError(
            "https://oauth2.googleapis.com/token", 400, "Bad Request",
            None, FakeErrorBody(),
        )

    monkeypatch.setattr(go, "urlopen", fake_urlopen)
    with pytest.raises(GoogleAuthError) as excinfo:
        go._exchange_code(
            "code", "cid", "csecret", "http://localhost:8765/oauth2callback"
        )
    assert "invalid or was already used" in str(excinfo.value)


def test_start_sign_in_returns_error_when_unconfigured(monkeypatch):
    from auth import google_oauth as go

    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    err = go.start_sign_in("flow-unconfigured")
    assert err is not None
    assert "not configured" in err
    assert go.get_flow_status("flow-unconfigured")["status"] == "done"


def test_flow_status_lifecycle(monkeypatch):
    import time as _time

    from auth import google_oauth as go

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(go, "_callback_port_in_use", lambda port: False)

    def fake_sign_in(timeout=180):
        _time.sleep(0.3)
        return {"email": "x@example.com", "name": "X", "verified_email": True}

    monkeypatch.setattr(go, "sign_in_with_google", fake_sign_in)

    assert go.start_sign_in("flow-life") is None
    assert go.get_flow_status("flow-life")["status"] == "running"
    _time.sleep(0.8)
    status = go.get_flow_status("flow-life")
    assert status["status"] == "done"
    assert status["profile"]["email"] == "x@example.com"
    go.clear_flow("flow-life")
    assert go.get_flow_status("flow-life")["status"] == "done"


def test_flow_error_is_captured(monkeypatch):
    import time as _time

    from auth import google_oauth as go

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(go, "_callback_port_in_use", lambda port: False)

    def failing_sign_in(timeout=180):
        raise GoogleAuthError("Google sign-in timed out \u2014 no browser response received.")

    monkeypatch.setattr(go, "sign_in_with_google", failing_sign_in)
    go.start_sign_in("flow-error")
    _time.sleep(0.5)
    status = go.get_flow_status("flow-error")
    assert status["status"] == "done"
    assert "timed out" in status["error"]
    go.clear_flow("flow-error")


def test_callback_port_in_use(monkeypatch):
    from auth import google_oauth as go

    class FakeSock:
        def __init__(self, result):
            self.result = result

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def connect_ex(self, addr):
            return self.result

    monkeypatch.setattr(go.socket, "socket", lambda *a, **k: FakeSock(0))
    assert go._callback_port_in_use(8765) is True
    monkeypatch.setattr(go.socket, "socket", lambda *a, **k: FakeSock(1))
    assert go._callback_port_in_use(8765) is False


def test_local_callback_server_closes_connection_and_shuts_down():
    """The local callback server must not hang on idle connections.

    Regression: the single-threaded HTTPServer kept the browser's
    callback connection alive (HTTP/1.1 keep-alive), so serve_forever()
    blocked reading the idle socket and server.shutdown() deadlocked -
    the flow thread never stored its result, the UI stayed on "Waiting
    for Google sign-in..." forever, and the callback port was leaked.
    """
    import socket
    import threading
    from http.server import HTTPServer

    from auth import google_oauth as go

    server = HTTPServer(("127.0.0.1", 0), go._CallbackHandler)
    port = server.server_address[1]
    go._CallbackHandler.result = None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        # Browser-style GET that would otherwise stay keep-alive open.
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        try:
            sock.sendall(
                b"GET /oauth2callback?code=x&state=y HTTP/1.1\r\n"
                b"Host: localhost\r\n\r\n"
            )
            data = sock.recv(4096)
            assert data.startswith(b"HTTP/1.0 200 OK")
            # Headers and body may arrive in separate TCP segments on
            # localhost - keep reading until the full body has arrived.
            while b"Signed in with Google" not in data:
                chunk = sock.recv(4096)
                assert chunk, "connection closed before the response completed"
                data += chunk
            assert b"Signed in with Google" in data
            assert go._CallbackHandler.result == {"code": ["x"], "state": ["y"]}
            # The server must close the connection after the response, so
            # serve_forever() is never parked on an idle keep-alive read.
            rest = sock.recv(4096)
            assert rest == b""
        finally:
            sock.close()

        # shutdown() must return promptly (before the fix this deadlocked).
        done = threading.Event()

        def _shutdown():
            server.shutdown()
            done.set()

        threading.Thread(target=_shutdown, daemon=True).start()
        assert done.wait(timeout=10), "server.shutdown() deadlocked"
    finally:
        server.server_close()


def test_config_report_never_logs_secrets(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "super-secret-value")
    lines = config_report()
    joined = "\n".join(lines)
    assert "super-secret-value" not in joined
    assert "Google Login: ENABLED" in joined
    assert "http://localhost:8765/oauth2callback" in joined


def test_login_oauth_creates_user_by_email():
    db = database.init_db(":memory:")
    auth = AuthService(db)
    user, token = auth.login_oauth("jane.doe@gmail.com", name="Jane Doe")
    assert token is not None
    assert user["email"] == "jane.doe@gmail.com"
    assert user["role"] == "developer"
    # second login reuses the same user
    user2, token2 = auth.login_oauth("jane.doe@gmail.com", name="Jane Doe")
    assert user2["id"] == user["id"]
    assert token2 is not None


def test_login_oauth_invalid_email():
    db = database.init_db(":memory:")
    auth = AuthService(db)
    user, token = auth.login_oauth("")
    assert user is None and token is None


def test_login_oauth_unique_usernames():
    db = database.init_db(":memory:")
    auth = AuthService(db)
    u1, _ = auth.login_oauth("bob@gmail.com")
    u2, _ = auth.login_oauth("bob@outlook.com")
    assert u1["username"] != u2["username"]
    assert u1["username"].startswith("bob")
    assert u2["username"].startswith("bob")


# ----------------------------------------------------------------------
# Public (deployed / permanent public URL) flow - GOOGLE_REDIRECT_URI
# ----------------------------------------------------------------------
def _set_public_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv(
        "GOOGLE_REDIRECT_URI", "https://app.example.com/oauth2callback"
    )


def test_public_flow_detection(monkeypatch):
    from auth import google_oauth as go

    _set_public_env(monkeypatch)
    assert go.is_public_flow() is True
    assert (
        go.get_public_redirect_uri()
        == "https://app.example.com/oauth2callback"
    )
    assert (
        go.get_effective_redirect_uri()
        == "https://app.example.com/oauth2callback"
    )
    report = go.validate_config()
    assert report["public"] is True
    assert report["redirect_uri"] == "https://app.example.com/oauth2callback"
    assert report["enabled"] is True


def test_public_redirect_uri_must_be_absolute_without_query(monkeypatch):
    from auth import google_oauth as go

    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "not-a-url")
    assert go.get_public_redirect_uri() is None
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://x.com/cb?q=1")
    assert go.get_public_redirect_uri() is None


def test_start_sign_in_public_mode_stores_auth_url(monkeypatch):
    from auth import google_oauth as go

    _set_public_env(monkeypatch)
    monkeypatch.setattr(go.webbrowser, "open", lambda url: False)
    assert go.start_sign_in("flow-pub") is None
    status = go.get_flow_status("flow-pub")
    assert status["status"] == "running"
    assert status["auth_url"].startswith(go.GOOGLE_AUTH_URL)
    assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Foauth2callback" in (
        status["auth_url"]
    )
    assert status.get("state")
    go.clear_flow("flow-pub")
    assert go.get_flow_status("flow-pub")["status"] == "done"


def test_start_public_sign_in_requires_redirect_uri(monkeypatch):
    from auth import google_oauth as go

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.delenv("GOOGLE_REDIRECT_URI", raising=False)
    # Without GOOGLE_REDIRECT_URI the app stays in localhost mode.
    assert go.is_public_flow() is False
    err = go.start_public_sign_in("flow-nopub")
    assert err is not None
    assert "GOOGLE_REDIRECT_URI" in err


def test_complete_public_callback_exchanges_and_stores(monkeypatch):
    from auth import google_oauth as go

    _set_public_env(monkeypatch)
    monkeypatch.setattr(go.webbrowser, "open", lambda url: False)
    assert go.start_sign_in("flow-cb") is None
    state = go.get_flow_status("flow-cb")["state"]

    monkeypatch.setattr(
        go, "_exchange_code", lambda *a, **k: {"access_token": "tok"}
    )
    monkeypatch.setattr(go, "_fetch_profile", lambda tok: {
        "email": "jane@gmail.com", "name": "Jane",
        "picture": "http://pic", "verified_email": True,
    })
    profile = go.complete_public_callback("the-code", state)
    assert profile["email"] == "jane@gmail.com"

    done = go.get_flow_status("flow-cb")
    assert done["status"] == "done"
    assert done["profile"]["email"] == "jane@gmail.com"
    # The state is single-use - a second completion must fail.
    with pytest.raises(GoogleAuthError):
        go.complete_public_callback("the-code-again", state)
    go.clear_flow("flow-cb")


def test_complete_public_callback_rejects_bad_state(monkeypatch):
    from auth import google_oauth as go

    _set_public_env(monkeypatch)
    monkeypatch.setattr(go.webbrowser, "open", lambda url: False)
    go.start_sign_in("flow-badstate")
    with pytest.raises(GoogleAuthError) as excinfo:
        go.complete_public_callback("code", "not-the-state")
    assert "expired" in str(excinfo.value)
    go.clear_flow("flow-badstate")


def test_complete_public_callback_unknown_state():
    from auth import google_oauth as go

    with pytest.raises(GoogleAuthError) as excinfo:
        go.complete_public_callback("code", "never-issued")
    assert "expired" in str(excinfo.value)


def test_complete_public_callback_error_param():
    from auth import google_oauth as go

    with pytest.raises(GoogleAuthError) as excinfo:
        go.complete_public_callback("", "", error="access_denied")
    assert "declined" in str(excinfo.value)


def test_public_flow_times_out(monkeypatch):
    from auth import google_oauth as go

    _set_public_env(monkeypatch)
    monkeypatch.setattr(go.webbrowser, "open", lambda url: False)
    # A negative timeout puts the deadline firmly in the past, so the
    # very next get_flow_status() reports the timeout deterministically.
    assert go.start_public_sign_in("flow-timeout", timeout=-5) is None
    status = go.get_flow_status("flow-timeout")
    assert status["status"] == "done"
    assert "timed out" in status["error"]
    go.clear_flow("flow-timeout")


def test_complete_public_sign_in_end_to_end(monkeypatch):
    import json as _json

    from auth import google_oauth as go

    _set_public_env(monkeypatch)
    state = go.new_state()
    url = go.build_public_auth_url(state)
    assert "client_id=abc.apps.googleusercontent.com" in url
    assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Foauth2callback" in url
    assert "state=" in url

    token_body = _json.dumps({"access_token": "tok-123"}).encode("utf-8")
    profile_body = _json.dumps({
        "email": "zoe@gmail.com", "name": "Zoe", "verified_email": True,
    }).encode("utf-8")
    calls = []

    def fake_urlopen(req, timeout=30):
        calls.append(req.full_url)

        class Resp:
            def read(self):
                if req.full_url == go.GOOGLE_TOKEN_URL:
                    return token_body
                return profile_body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return Resp()

    monkeypatch.setattr(go, "urlopen", fake_urlopen)
    profile = go.complete_public_sign_in("the-code", state, state)
    assert profile["email"] == "zoe@gmail.com"
    assert len(calls) == 2
    assert calls[0] == go.GOOGLE_TOKEN_URL
    assert calls[1] == go.GOOGLE_USERINFO_URL
