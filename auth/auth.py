"""Authentication & authorization service.

Provides:
    - password hashing (PBKDF2-HMAC-SHA256, salted, stdlib only)
    - user registration / login / logout
    - session tokens stored in the database
    - Role-Based Access Control (admin / developer / guest)

Sessions live in the `sessions` table, so any process (Streamlit UI,
REST API, CLI) can share the same authenticated identity.
"""
import hashlib
import hmac
import os
import secrets
import time

from database import get_db

# ----------------------------------------------------------------------
# Roles & permissions
# ----------------------------------------------------------------------
ROLES = ("admin", "developer", "guest")

# What each role is allowed to do (used by UI + REST API + guard rails).
ROLE_PERMISSIONS = {
    "admin": {
        "chat", "coding", "debugging", "documentation", "planner",
        "reviewer", "project_analysis", "code_analysis", "github",
        "workflow", "tools", "file_manager", "settings", "user_management",
        "reports", "dashboard", "monitoring",
    },
    "developer": {
        "chat", "coding", "debugging", "documentation", "planner",
        "reviewer", "project_analysis", "code_analysis", "github",
        "workflow", "tools", "file_manager", "reports", "dashboard",
        "monitoring",
    },
    "guest": {
        "chat", "code_analysis", "project_analysis", "github",
        "dashboard", "reports",
    },
}

SESSION_TTL_SECONDS = 60 * 60 * 12  # 12 hours


def hash_password(password, salt=None):
    """Return a salted PBKDF2-SHA256 hash string: salt$hexhash."""
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000
    ).hex()
    return f"{salt}${digest}"


def verify_password(password, stored):
    """Constant-time comparison against a stored hash string."""
    try:
        salt, expected = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hash_password(password, salt=salt)
    return hmac.compare_digest(candidate, stored)


class AuthService:
    """Thin wrapper around the database for all auth operations."""

    def __init__(self, db=None):
        self.db = db or get_db()

    # ------------------------------------------------------------------
    # Registration / login
    # ------------------------------------------------------------------
    def register(self, username, password, role="developer", email=None):
        """Create a user. Returns the user dict or None if username taken."""
        username = (username or "").strip()
        if not username or not password:
            raise ValueError("Username and password are required.")
        if self.db.get_user_by_username(username):
            return None
        if role not in ROLES:
            raise ValueError(f"Invalid role: {role}")
        return self.db.create_user(
            username, hash_password(password), role, email
        )

    def login(self, username, password):
        """Validate credentials and create a session.

        Returns (user_dict, token) on success, or (None, None).
        """
        user = self.db.get_user_by_username((username or "").strip())
        if not user or not verify_password(password, user["password_hash"]):
            return None, None
        return self._create_session(user)

    def login_by_email(self, email, password):
        """Login using the email address (matches email OR username).

        Returns (user_dict, token) on success, or (None, None).
        """
        email = (email or "").strip().lower()
        if not email or not password:
            return None, None
        user = self.db.get_user_by_email(email)
        if not user:
            # Allow users who registered with their email as the username.
            user = self.db.get_user_by_username(email)
        if not user or not verify_password(password, user["password_hash"]):
            return None, None
        return self._create_session(user)

    def login_oauth(self, email, name=None):
        """Login or auto-register a user from an external OAuth profile.

        Finds an existing user by email, otherwise creates one on the fly
        with a random password (they can only sign in via the provider).
        Returns (user_dict, token) or (None, None).
        """
        email = (email or "").strip().lower()
        if not email:
            return None, None
        user = self.db.get_user_by_email(email)
        if not user:
            base = (name or email.split("@")[0] or "user").strip()[:24] or "user"
            username, n = base, 1
            while self.db.get_user_by_username(username):
                n += 1
                username = f"{base}{n}"
            user = self.register(
                username,
                secrets.token_urlsafe(24),
                role="developer",
                email=email,
            )
            if not user:
                return None, None
        return self._create_session(user)

    def login_guest(self):
        """Create (or reuse) a guest identity and open a session.

        Guests get a random, unusable password hash so they can only
        ever enter through the "Continue as Guest" button.
        """
        user = self.db.get_user_by_username("guest")
        if not user:
            user = self.register(
                "guest", secrets.token_urlsafe(32),
                role="guest", email="guest@local",
            )
        return self._create_session(user)

    def _create_session(self, user):
        token = secrets.token_urlsafe(32)
        expires = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(time.time() + SESSION_TTL_SECONDS),
        )
        self.db.create_session(token, user["id"], expires)
        return user, token

    def logout(self, token):
        if token:
            self.db.delete_session(token)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def get_session_user(self, token):
        """Return the user dict for a valid token, else None.

        Expired sessions are treated as invalid (and cleaned up).
        """
        if not token:
            return None
        session = self.db.get_session(token)
        if not session:
            return None
        # Expiry check (string comparison works for the ISO-like format)
        if session["expires_at"] < time.strftime("%Y-%m-%d %H:%M:%S"):
            self.db.delete_session(token)
            return None
        return {
            "id": session["user_id"],
            "username": session["username"],
            "role": session["role"],
        }

    # ------------------------------------------------------------------
    # RBAC helpers
    # ------------------------------------------------------------------
    def has_permission(self, role, permission):
        return permission in ROLE_PERMISSIONS.get(role, set())

    def require_role(self, user, *allowed_roles):
        if not user or user.get("role") not in allowed_roles:
            return False
        return True

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------
    def ensure_default_admin(self, password=None):
        """Create a default 'admin' account on first run (idempotent).

        Uses the ADMIN_PASSWORD env var when set; otherwise falls back to
        a well-known default and prints a warning so operators change it.
        """
        if self.db.get_user_by_username("admin"):
            return None
        password = password or os.getenv("ADMIN_PASSWORD")
        if not password:
            password = "admin123"
            print(
                "\n⚠️  DEFAULT ADMIN CREATED: username='admin' "
                "password='admin123'. Set ADMIN_PASSWORD in .env to override.\n"
            )
        return self.register("admin", password, role="admin", email="admin@local")
