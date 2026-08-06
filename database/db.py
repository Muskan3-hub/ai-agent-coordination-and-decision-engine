"""Enterprise database layer.

SQLite by default (zero-config). The schema is intentionally written in
a dialect-neutral way so a PostgreSQL backend can be swapped in later by
changing the connection string / using the `DATABASE_URL` env var.

Tables:
    users, sessions, conversations, messages, memory_facts,
    workflows, executions, tool_logs, agent_logs, analytics,
    github_activity, projects, settings
"""
import json
import os
import sqlite3
import threading
import time

DB_PATH = os.getenv("DATABASE_URL", "enterprise.db")
if DB_PATH.startswith(("postgres", "postgresql")):
    raise RuntimeError(
        "PostgreSQL backend requires psycopg2. Set DATABASE_URL to a "
        "sqlite path, or install psycopg2-binary and enable the postgres "
        "driver in database/db.py."
    )

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'developer',
    email         TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token      TEXT UNIQUE NOT NULL,
    user_id    INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    title      TEXT NOT NULL DEFAULT 'New chat',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    agent           TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message_attachments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      INTEGER NOT NULL,
    conversation_id INTEGER NOT NULL,
    file_id         TEXT NOT NULL,
    file_name       TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    topic      TEXT NOT NULL,
    value      TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflows (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    task            TEXT NOT NULL,
    planner         TEXT,
    coding          TEXT,
    review          TEXT,
    code_analysis   TEXT,
    documentation   TEXT,
    status          TEXT NOT NULL DEFAULT 'completed',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS executions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    agent       TEXT NOT NULL,
    status      TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tool       TEXT NOT NULL,
    action     TEXT,
    status     TEXT,
    detail     TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent      TEXT NOT NULL,
    action     TEXT,
    status     TEXT,
    detail     TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event      TEXT NOT NULL,
    detail     TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS github_activity (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    action     TEXT NOT NULL,
    owner      TEXT,
    repo       TEXT,
    status     TEXT,
    detail     TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    name         TEXT NOT NULL,
    path         TEXT,
    summary      TEXT,
    health_score INTEGER,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class Database:
    """Thin, thread-safe data access layer over SQLite.

    Every method commits immediately and opens a fresh connection, so it
    is safe to share a single Database instance across threads (Streamlit
    reruns, background tasks, the REST API).
    """

    def __init__(self, path=None):
        self.path = path or DB_PATH
        self._lock = threading.Lock()
        # In-memory databases must share ONE persistent connection,
        # otherwise the schema created in __init__ disappears on the
        # next connect. File-backed databases get a fresh connection
        # per call (safe for cross-thread use).
        self._memory_conn = None
        self._ensure_schema()

    def _connect(self):
        if self.path == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(
                    ":memory:", timeout=30
                )
                self._memory_conn.row_factory = sqlite3.Row
            return self._memory_conn
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self):
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(SCHEMA)
                conn.commit()
            finally:
                if self.path != ":memory:":
                    conn.close()

    def _execute(self, sql, params=()):
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                return cur
            finally:
                if self.path != ":memory:":
                    conn.close()

    def _query(self, sql, params=()):
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
                return rows
            finally:
                if self.path != ":memory:":
                    conn.close()

    def _query_one(self, sql, params=()):
        rows = self._query(sql, params)
        return rows[0] if rows else None

    @staticmethod
    def _now():
        return time.strftime("%Y-%m-%d %H:%M:%S")

    # -------------------------------------------------------------
    # Users / auth
    # -------------------------------------------------------------
    def create_user(self, username, password_hash, role="developer", email=None):
        self._execute(
            "INSERT INTO users (username, password_hash, role, email, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, password_hash, role, email, self._now()),
        )
        return self.get_user_by_username(username)

    def get_user_by_username(self, username):
        return self._query_one(
            "SELECT * FROM users WHERE username = ?", (username,)
        )

    def get_user_by_email(self, email):
        return self._query_one(
            "SELECT * FROM users WHERE email = ?", (email,)
        )

    def get_user_by_id(self, user_id):
        return self._query_one("SELECT * FROM users WHERE id = ?", (user_id,))

    def list_users(self):
        return self._query(
            "SELECT id, username, role, email, created_at FROM users ORDER BY id"
        )

    def create_session(self, token, user_id, expires_at):
        self._execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (token, user_id, self._now(), expires_at),
        )

    def get_session(self, token):
        return self._query_one(
            "SELECT s.*, u.username, u.role FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        )

    def delete_session(self, token):
        self._execute("DELETE FROM sessions WHERE token = ?", (token,))

    # -------------------------------------------------------------
    # Conversations
    # -------------------------------------------------------------
    def create_conversation(self, user_id, title="New chat"):
        cur = self._execute(
            "INSERT INTO conversations (user_id, title, created_at) VALUES (?, ?, ?)",
            (user_id, title, self._now()),
        )
        return cur.lastrowid

    def list_conversations(self, user_id, limit=50):
        return self._query(
            "SELECT c.*, "
            "(SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) "
            "AS msg_count "
            "FROM conversations c WHERE c.user_id = ? "
            "ORDER BY c.id DESC LIMIT ?",
            (user_id, limit),
        )

    def get_conversation(self, conversation_id):
        return self._query_one(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        )

    def update_conversation_title(self, conversation_id, title):
        self._execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            (title, conversation_id),
        )

    def delete_conversation(self, conversation_id):
        self._execute(
            "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
        )
        self._execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,)
        )

    def add_message(self, conversation_id, role, content, agent=None):
        """Insert a message and return its new id."""
        cur = self._execute(
            "INSERT INTO messages (conversation_id, role, content, agent, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, content, agent, self._now()),
        )
        return cur.lastrowid

    def list_messages(self, conversation_id):
        return self._query(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        )

    # -------------------------------------------------------------
    # Message attachments (persisted user-uploaded files)
    # -------------------------------------------------------------
    def attach_message_file(self, message_id, conversation_id, file_id, file_name):
        self._execute(
            "INSERT INTO message_attachments "
            "(message_id, conversation_id, file_id, file_name, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (message_id, conversation_id, file_id, file_name, self._now()),
        )

    def list_message_attachments(self, conversation_id):
        """Return {message_id: [{id, name}, ...]} for a conversation."""
        rows = self._query(
            "SELECT message_id, file_id, file_name FROM message_attachments "
            "WHERE conversation_id = ?",
            (conversation_id,),
        )
        out = {}
        for r in rows:
            out.setdefault(r["message_id"], []).append(
                {"id": r["file_id"], "name": r["file_name"]}
            )
        return out

    def search_messages(self, user_id, query, limit=50):
        """Full-text-ish search across a user's messages."""
        like = f"%{query}%"
        return self._query(
            "SELECT m.id AS message_id, m.conversation_id, m.role, m.content, "
            "m.created_at, c.title AS conversation_title "
            "FROM messages m JOIN conversations c ON c.id = m.conversation_id "
            "WHERE c.user_id = ? AND m.content LIKE ? "
            "ORDER BY m.id DESC LIMIT ?",
            (user_id, like, limit),
        )

    # -------------------------------------------------------------
    # Memory facts
    # -------------------------------------------------------------
    def store_fact(self, user_id, topic, value):
        self._execute(
            "DELETE FROM memory_facts WHERE user_id = ? AND topic = ?",
            (user_id, topic),
        )
        self._execute(
            "INSERT INTO memory_facts (user_id, topic, value, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, topic, value, self._now()),
        )

    def get_facts(self, user_id):
        return self._query(
            "SELECT topic, value FROM memory_facts WHERE user_id = ?",
            (user_id,),
        )

    # -------------------------------------------------------------
    # Workflows
    # -------------------------------------------------------------
    def save_workflow(self, user_id, task, results, status="completed"):
        self._execute(
            "INSERT INTO workflows (user_id, task, planner, coding, review, "
            "code_analysis, documentation, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                task,
                results.get("planner"),
                results.get("coding"),
                results.get("review"),
                results.get("code_analysis"),
                results.get("documentation"),
                status,
                self._now(),
            ),
        )

    def count_workflows(self, user_id=None):
        if user_id is None:
            return self._query_one("SELECT COUNT(*) AS n FROM workflows")["n"]
        return self._query_one(
            "SELECT COUNT(*) AS n FROM workflows WHERE user_id = ?", (user_id,)
        )["n"]

    # -------------------------------------------------------------
    # Executions / analytics
    # -------------------------------------------------------------
    def log_execution(self, user_id, agent, status, duration_ms):
        self._execute(
            "INSERT INTO executions (user_id, agent, status, duration_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, agent, status, duration_ms, self._now()),
        )

    def log_tool(self, tool, action=None, status=None, detail=None):
        self._execute(
            "INSERT INTO tool_logs (tool, action, status, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (tool, action, status, detail, self._now()),
        )

    def log_agent(self, agent, action=None, status=None, detail=None):
        self._execute(
            "INSERT INTO agent_logs (agent, action, status, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (agent, action, status, detail, self._now()),
        )

    def log_analytics(self, event, detail=None):
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail)
        self._execute(
            "INSERT INTO analytics (event, detail, created_at) VALUES (?, ?, ?)",
            (event, detail, self._now()),
        )

    def log_github(self, action, owner=None, repo=None, status=None, detail=None):
        self._execute(
            "INSERT INTO github_activity (action, owner, repo, status, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (action, owner, repo, status, detail, self._now()),
        )

    # -------------------------------------------------------------
    # Projects
    # -------------------------------------------------------------
    def save_project(self, user_id, name, path=None, summary=None, health_score=None):
        self._execute(
            "INSERT INTO projects (user_id, name, path, summary, health_score, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, name, path, summary, health_score, self._now()),
        )

    def list_projects(self, user_id=None):
        if user_id is None:
            return self._query("SELECT * FROM projects ORDER BY id DESC")
        return self._query(
            "SELECT * FROM projects WHERE user_id = ? ORDER BY id DESC", (user_id,)
        )

    # -------------------------------------------------------------
    # Settings (key-value)
    # -------------------------------------------------------------
    def get_setting(self, key, default=None):
        row = self._query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key, value):
        self._execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, str(value), self._now()),
        )

    # -------------------------------------------------------------
    # Dashboard queries
    # -------------------------------------------------------------
    def dashboard_stats(self):
        """Aggregated numbers for the analytics dashboard."""

        def count(table, where=None, params=()):
            sql = f"SELECT COUNT(*) AS n FROM {table}"
            if where:
                sql += f" WHERE {where}"
            return self._query_one(sql, params)["n"]

        def avg_response_ms():
            row = self._query_one("SELECT AVG(duration_ms) AS a FROM executions")
            return int(row["a"]) if row and row["a"] else 0

        def most_used_agent():
            row = self._query_one(
                "SELECT agent, COUNT(*) AS n FROM executions "
                "GROUP BY agent ORDER BY n DESC LIMIT 1"
            )
            return (row["agent"], row["n"]) if row else (None, 0)

        def most_used_tool():
            row = self._query_one(
                "SELECT tool, COUNT(*) AS n FROM tool_logs "
                "GROUP BY tool ORDER BY n DESC LIMIT 1"
            )
            return (row["tool"], row["n"]) if row else (None, 0)

        def agent_usage():
            return self._query(
                "SELECT agent, COUNT(*) AS n FROM executions "
                "GROUP BY agent ORDER BY n DESC"
            )

        def tool_usage():
            return self._query(
                "SELECT tool, COUNT(*) AS n FROM tool_logs "
                "GROUP BY tool ORDER BY n DESC"
            )

        def recent_requests(limit=10):
            return self._query(
                "SELECT agent, status, duration_ms, created_at FROM executions "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            )

        ok = count("executions", "status = 'success'")
        total = count("executions")
        # With zero executions there is no data to show a percentage for -
        # report 0 instead of a fabricated 100%.
        success_rate = round(100 * ok / total, 1) if total else 0.0

        return {
            "total_conversations": count("conversations"),
            "total_messages": count("messages"),
            "total_workflows": count("workflows"),
            "total_executions": total,
            "avg_response_ms": avg_response_ms(),
            "success_rate": success_rate,
            "error_count": total - ok,
            "most_used_agent": most_used_agent(),
            "most_used_tool": most_used_tool(),
            "github_requests": count("github_activity"),
            "project_analyses": count("projects"),
            "memory_facts": count("memory_facts"),
            "agent_usage": agent_usage(),
            "tool_usage": tool_usage(),
            "recent_requests": recent_requests(),
        }

    # -------------------------------------------------------------
    # User-scoped dashboard helpers (read-only, used by the UI)
    # -------------------------------------------------------------
    def user_dashboard_stats(self, user_id):
        """Per-user aggregates for the analytics dashboard.

        Every number is derived from real records only - empty sessions
        (a conversation row created by clicking "New chat" but with no
        messages) are excluded, and with zero executions the success rate
        is 0 (never a fabricated 100%).
        """
        convs = self._query_one(
            "SELECT COUNT(*) AS n FROM conversations c WHERE c.user_id = ? "
            "AND EXISTS (SELECT 1 FROM messages m "
            "WHERE m.conversation_id = c.id)",
            (user_id,),
        )["n"]
        total = self._query_one(
            "SELECT COUNT(*) AS n FROM executions WHERE user_id = ?", (user_id,)
        )["n"]
        avg = self._query_one(
            "SELECT AVG(duration_ms) AS a FROM executions WHERE user_id = ?", (user_id,)
        )
        ok = self._query_one(
            "SELECT COUNT(*) AS n FROM executions WHERE user_id = ? "
            "AND status = 'success'",
            (user_id,),
        )["n"]
        workflows = self._query_one(
            "SELECT COUNT(*) AS n FROM workflows WHERE user_id = ?", (user_id,)
        )["n"]
        return {
            "total_conversations": convs,
            "total_executions": total,
            "total_workflows": workflows,
            "avg_response_ms": int(avg["a"]) if avg and avg["a"] else 0,
            "success_rate": round(100 * ok / total, 1) if total else 0.0,
            "error_count": total - ok,
        }

    def executions_by_day(self, user_id=None, limit=14):
        """Executions grouped by day (most recent first)."""
        where, params = "", ()
        if user_id is not None:
            where = " WHERE user_id = ?"
            params = (user_id,)
        return self._query(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n, "
            "AVG(duration_ms) AS avg_ms, "
            "SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS ok "
            f"FROM executions{where} GROUP BY day ORDER BY day DESC LIMIT ?",
            params + (limit,),
        )

    def conversations_by_day(self, user_id=None, limit=14):
        """Conversations grouped by day (most recent first)."""
        where, params = "", ()
        if user_id is not None:
            where = " WHERE user_id = ?"
            params = (user_id,)
        return self._query(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n "
            f"FROM conversations{where} GROUP BY day ORDER BY day DESC LIMIT ?",
            params + (limit,),
        )

    def workflows_by_day(self, user_id=None, limit=14):
        """Workflows grouped by day (most recent first)."""
        where, params = "", ()
        if user_id is not None:
            where = " WHERE user_id = ?"
            params = (user_id,)
        return self._query(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n "
            f"FROM workflows{where} GROUP BY day ORDER BY day DESC LIMIT ?",
            params + (limit,),
        )

    # -------------------------------------------------------------
    # Conversation lifecycle helpers (used by the UI)
    # -------------------------------------------------------------
    def delete_all_conversations(self, user_id):
        """Remove every conversation + message for a user. Returns count."""
        rows = self._query(
            "SELECT id FROM conversations WHERE user_id = ?", (user_id,)
        )
        ids = [r["id"] for r in rows]
        for cid in ids:
            self._execute("DELETE FROM messages WHERE conversation_id = ?", (cid,))
            self._execute("DELETE FROM conversations WHERE id = ?", (cid,))
        return len(ids)

    def delete_last_message(self, conversation_id, role="assistant"):
        """Remove the most recent message of a given role. Returns bool."""
        rows = self._query(
            "SELECT id FROM messages WHERE conversation_id = ? AND role = ? "
            "ORDER BY id DESC LIMIT 1",
            (conversation_id, role),
        )
        if not rows:
            return False
        self._execute("DELETE FROM messages WHERE id = ?", (rows[0]["id"],))
        return True

    def export_conversations(self, user_id):
        """Return all conversations (with messages) for export as JSON."""
        out = []
        for conv in self.list_conversations(user_id, limit=1000):
            out.append(
                {
                    "id": conv["id"],
                    "title": conv["title"],
                    "created_at": conv["created_at"],
                    "messages": self.list_messages(conv["id"]),
                }
            )
        return out


# -------------------------------------------------------------
# Module-level singleton + bootstrap
# -------------------------------------------------------------
_db = None
_db_lock = threading.Lock()


def get_db():
    """Return a process-wide Database singleton."""
    global _db
    with _db_lock:
        if _db is None:
            _db = Database()
        return _db


def init_db(path=None):
    """Force (re)initialization - used by tests and CLI bootstrap."""
    global _db
    with _db_lock:
        _db = Database(path=path)
        return _db
