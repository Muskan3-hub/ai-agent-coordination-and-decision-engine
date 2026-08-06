"""Tests for the enterprise database layer."""
import database
from auth import AuthService


def test_database_schema_and_users():
    db = database.init_db(":memory:")
    db.create_user("alice", "hash1", role="admin")
    user = db.get_user_by_username("alice")
    assert user["role"] == "admin"
    assert len(db.list_users()) == 1


def test_conversations_and_messages():
    db = database.init_db(":memory:")
    user = db.create_user("bob", "hash", role="developer")
    conv_id = db.create_conversation(user["id"], title="Chat 1")
    db.add_message(conv_id, "user", "hello")
    db.add_message(conv_id, "assistant", "hi!", agent="Chat Assistant")
    msgs = db.list_messages(conv_id)
    assert len(msgs) == 2
    assert msgs[1]["agent"] == "Chat Assistant"
    assert len(db.list_conversations(user["id"])) == 1


def test_memory_facts_and_settings():
    db = database.init_db(":memory:")
    db.store_fact(1, "name", "Muskan")
    db.store_fact(1, "name", "Updated")
    facts = db.get_facts(1)
    assert len(facts) == 1
    assert facts[0]["value"] == "Updated"

    db.set_setting("theme", "dark")
    assert db.get_setting("theme") == "dark"
    assert db.get_setting("missing", "fallback") == "fallback"


def test_workflows_executions_projects():
    db = database.init_db(":memory:")
    db.save_workflow(1, "Build a calculator", {
        "planner": "plan", "coding": "code", "review": "review",
        "code_analysis": "analysis", "documentation": "docs",
    })
    assert db.count_workflows() == 1

    db.log_execution(1, "Coding Agent", "success", 250)
    db.log_execution(1, "Chat Agent", "error", 100)
    db.log_tool("FileTool", "write", "SUCCESS", "ok")
    db.log_github("repo_info", "tensorflow", "tensorflow", "SUCCESS", "ok")

    stats = db.dashboard_stats()
    assert stats["total_executions"] == 2
    assert stats["total_workflows"] == 1
    assert stats["github_requests"] == 1
    assert stats["success_rate"] == 50.0
    assert stats["most_used_agent"][0] in ("Coding Agent", "Chat Agent")

    db.save_project(1, "proj", ".", "summary", 90)
    assert len(db.list_projects(1)) == 1


def test_sessions_auth_integration():
    db = database.init_db(":memory:")
    auth = AuthService(db)
    auth.ensure_default_admin()
    user, token = auth.login("admin", "admin123")
    assert user is not None
    session_user = auth.get_session_user(token)
    assert session_user["username"] == "admin"
    auth.logout(token)
    assert auth.get_session_user(token) is None


def test_conversation_helpers_and_per_user_isolation():
    db = database.init_db(":memory:")
    alice = db.create_user("alice", "hash", role="developer")
    bob = db.create_user("bob", "hash", role="developer")

    a_conv = db.create_conversation(alice["id"], title="New session")
    b_conv = db.create_conversation(bob["id"], title="New session")

    # Titles can be updated (ChatGPT-style naming)
    db.update_conversation_title(a_conv, "Build a calculator")
    conv = db.get_conversation(a_conv)
    assert conv["title"] == "Build a calculator"
    assert conv["user_id"] == alice["id"]

    # Each user only ever sees their own conversations
    assert [c["id"] for c in db.list_conversations(alice["id"])] == [a_conv]
    assert [c["id"] for c in db.list_conversations(bob["id"])] == [b_conv]

    # Messages are scoped to their conversation
    db.add_message(a_conv, "user", "hello alice")
    assert len(db.list_messages(a_conv)) == 1
    assert len(db.list_messages(b_conv)) == 0

    # Deleting a conversation removes its messages too
    db.delete_conversation(a_conv)
    assert db.get_conversation(a_conv) is None
    assert db.list_messages(a_conv) == []
    assert len(db.list_conversations(alice["id"])) == 0
    assert len(db.list_conversations(bob["id"])) == 1
