"""Tests for the Google OAuth helpers and OAuth-based auth flows."""
import pytest

from auth import AuthService
from auth.google_oauth import (
    GoogleAuthError,
    is_configured,
    sign_in_with_google,
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


def test_sign_in_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    with pytest.raises(GoogleAuthError):
        sign_in_with_google(timeout=1)


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
