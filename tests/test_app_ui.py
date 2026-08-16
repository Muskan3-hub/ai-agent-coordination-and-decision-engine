"""UI smoke tests via Streamlit's AppTest harness (no LLM calls).

Verifies the consumer-grade flows of the UI upgrade without needing a
browser: guest login opens the workspace, the + composer menu lists the
attach/action entries, and chat actions are only Rename / Pin / Share /
Delete (no Duplicate, no JSON export). AppTest renders popover content
eagerly, so the menu entries can be asserted directly after login.
"""
import os
import secrets
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="AppTest needs the exact interpreter version",
)


@pytest.fixture(autouse=True)
def _fresh_db():
    """Isolate every UI test from the process-wide Database singleton.

    Other test files swap the shared singleton to a fresh in-memory
    database, and the real enterprise.db may contain leftover chats -
    either way the rendered sidebar depends on state this file does not
    control. A fresh in-memory database per test keeps these UI tests
    deterministic and independent of the rest of the suite.
    """
    from database import init_db

    init_db(":memory:")
    yield


def _seed_guest_chat():
    """Create the guest user plus one conversation with messages, so the
    sidebar renders chat rows with their actions menu (Rename / Pin /
    Share / Delete) after guest login."""
    from auth import AuthService
    from database import get_db

    db = get_db()
    auth = AuthService(db)
    user = db.get_user_by_username("guest")
    if not user:
        user = auth.register(
            "guest", secrets.token_urlsafe(32),
            role="guest", email="guest@local",
        )
    cid = db.create_conversation(user["id"], title="Seed chat")
    db.add_message(cid, "user", "hello")
    db.add_message(cid, "assistant", "hi there")
    return user


def _run():
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    return at


def _guest_login(at):
    btn = next(
        (b for b in at.button if "Continue as Guest" in (b.label or "")), None
    )
    assert btn is not None, "guest button missing"
    btn.click()
    at.run()
    try:
        assert at.session_state["user"] is not None, "guest login failed"
    except KeyError:
        pytest.fail("guest login failed - no user in session")


def test_login_page_renders():
    at = _run()
    assert any("Welcome back" in (m.value or "") for m in at.markdown)


def test_guest_login_opens_workspace():
    at = _run()
    _guest_login(at)
    labels = [b.label for b in at.button]
    assert any("New chat" in (l or "") for l in labels), "workspace header missing"
    assert any("guest" in (b.label or "").lower() for b in at.button), (
        "profile menu trigger missing"
    )


def test_composer_plus_menu_lists_actions():
    at = _run()
    _guest_login(at)
    labels = [b.label for b in at.button]
    for entry in (
        "Upload File", "Build Application", "Write Code",
        "Debug", "Documentation", "Analyze Project", "Code Analysis",
    ):
        assert any(entry in (l or "") for l in labels), f"+ menu missing: {entry}"
    # The removed image-upload feature must not reappear.
    assert not any("Upload Image" in (l or "") for l in labels), (
        "Upload Image must be removed from the + menu"
    )
    # The dedicated Upload Project button is removed, but the project
    # quick action and ZIP handling remain.
    assert not any("Upload Project" in (l or "") for l in labels), (
        "Upload Project button must be removed from the + menu"
    )


def test_chat_actions_are_rename_pin_share_delete_only():
    # Seed a conversation first so the sidebar renders chat rows and
    # their actions menu (a brand-new account has no rows yet).
    _seed_guest_chat()
    at = _run()
    _guest_login(at)
    labels = [b.label for b in at.button]
    assert any("Rename" in (l or "") for l in labels), "Rename missing"
    assert any("Share" in (l or "") for l in labels), "Share missing"
    assert any("Delete" in (l or "") for l in labels), "Delete missing"
    assert any("Pin" in (l or "") or "Unpin" in (l or "") for l in labels)
    assert not any("Duplicate" in (l or "") for l in labels), (
        "Duplicate Chat must be removed"
    )
    assert not any("JSON" in (l or "") for l in labels), (
        "JSON export must be removed from chat actions"
    )


def test_profile_menu_entries_present():
    at = _run()
    _guest_login(at)
    labels = [b.label for b in at.button]
    for entry in ("User Profile", "Settings", "Help Center",
                  "Terms & Privacy", "Logout"):
        assert any(entry in (l or "") for l in labels), f"profile menu missing {entry}"


def _logged_in_session():
    """Return an AppTest with a pre-seeded user session.

    Seeding the session skips the login flow entirely, which lets a test
    click the profile menu and rerun multiple times (the login form's
    widgets are never rendered, avoiding AppTest's stale-widget quirk on
    a third rerun).
    """
    at = AppTest.from_file("app.py", default_timeout=60)
    at.session_state["user"] = {"id": 1, "username": "admin", "role": "admin"}
    at.session_state["token"] = "test-token"
    at.run()
    return at


def test_profile_menu_navigates_to_settings_and_profile():
    """Regression: the sidebar nav radio used to share its key with the
    page-state variable, so a single-option radio overrode programmatic
    navigation - Settings / Profile from the profile menu never opened.
    """
    at = _logged_in_session()
    assert at.session_state["nav_radio"] == "workspace"

    # Settings from the profile popover opens the Settings page.
    at.button(key="prof_settings").click()
    at.run()
    assert at.session_state["nav_radio"] == "settings"
    md = " ".join(m.value or "" for m in at.markdown)
    assert "Make the assistant yours" in md, "Settings page not rendered"

    # Profile from the profile popover opens the Profile page.
    at.button(key="prof_profile").click()
    at.run()
    assert at.session_state["nav_radio"] == "profile"
    md = " ".join(m.value or "" for m in at.markdown)
    assert "Your account at a glance" in md, "Profile page not rendered"

    # The sidebar Home button returns to the workspace.
    at.button(key="side_home").click()
    at.run()
    assert at.session_state["nav_radio"] == "workspace"
    md = " ".join(m.value or "" for m in at.markdown)
    assert "What can I help you build today" in md, "Workspace not rendered"


def test_upload_and_followup_context(monkeypatch):
    """Upload a file, ask about it, then follow up.

    The attachment stays attached for the whole conversation and every
    prompt carries its context - so follow-ups ("Review the above
    code") work with no re-uploading. The coordinator is stubbed so the
    test captures exactly what prompt the app would have sent.
    """
    import memory.memory as mem_mod

    monkeypatch.setattr(mem_mod, "save_history", lambda h: None)

    from agents.coordinator import CoordinatorAgent

    captured = []

    def fake_handle_task(self, task, progress_callback=None):
        captured.append(task)
        return {"response": "Understood - here is the answer.",
                "agent": "Chat Assistant"}

    monkeypatch.setattr(CoordinatorAgent, "handle_task", fake_handle_task)

    # Unique user id so uploads land in their own directory.
    test_uid = 999
    uploads_dir = os.path.join("user_data", "uploads", str(test_uid))
    os.makedirs(uploads_dir, exist_ok=True)
    try:
        at = AppTest.from_file("app.py", default_timeout=90)
        at.session_state["user"] = {
            "id": test_uid, "username": "tester", "role": "admin",
        }
        at.session_state["token"] = "test-token"
        at.run()

        def attached():
            try:
                return list(at.session_state["_attached"])
            except Exception:
                return []

        def open_uploader(action):
            at.session_state["_attach_action"] = action
            at.run()
            return at.file_uploader(key="attach_upload")

        hello = b"def greet(name):\n    return f'Hello, {name}'\n"

        # Upload a file - it stays attached for the whole conversation.
        fu = open_uploader("upload_file")
        assert fu is not None, "Upload File must open an uploader"
        fu.upload("hello.py", hello, "text/x-python")
        at.run()
        assert len(attached()) == 1, "hello.py should be attached"

        # Duplicate uploads are prevented (same name + size).
        fu2 = open_uploader("upload_file")
        fu2.upload("hello.py", hello, "text/x-python")
        at.run()
        assert len(attached()) == 1, "duplicate upload must be prevented"

        # Q1: ask about the upload - prompt carries the file context.
        at.chat_input(key="chat_input").set_value("What does hello.py do?")
        at.run()
        assert len(captured) == 1
        assert "[Attached file: hello.py]" in captured[0]
        assert "def greet" in captured[0], "file content must be inlined"
        assert len(attached()) == 1, "attachment stays for follow-ups"

        # Q2: terse follow-up - context persists with no re-upload.
        at.chat_input(key="chat_input").set_value(
            "Review the above code and fix any bugs"
        )
        at.run()
        assert len(captured) == 2
        assert "[Attached file: hello.py]" in captured[1]
        assert "Previous assistant response" in captured[1], (
            "follow-up must also carry the previous response"
        )
    finally:
        for name in os.listdir(uploads_dir):
            os.remove(os.path.join(uploads_dir, name))
        os.rmdir(uploads_dir)


def test_followup_after_reopen_carries_workflow_code(monkeypatch):
    """Regression: a follow-up in a conversation reopened from the DB must
    carry the previously generated code (recovered from the markdown
    fences), not just the truncated plan text.

    The DB stores only the rendered markdown response - loaded messages
    have no explicit ``code`` field - so the app must re-extract the
    fenced code block for the follow-up prompt.
    """
    import memory.memory as mem_mod

    monkeypatch.setattr(mem_mod, "save_history", lambda h: None)

    from agents.coordinator import CoordinatorAgent

    captured = []

    def fake_handle_task(self, task, progress_callback=None):
        captured.append(task)
        return {"response": "ok", "agent": "Chat Assistant"}

    monkeypatch.setattr(CoordinatorAgent, "handle_task", fake_handle_task)

    at = AppTest.from_file("app.py", default_timeout=60)
    at.session_state["user"] = {
        "id": 998, "username": "tester", "role": "admin",
    }
    at.session_state["token"] = "test-token"
    # Simulate a reopened conversation: the assistant message is a long
    # markdown workflow response whose code lives in a ```python fence.
    at.session_state["messages"] = [
        {"role": "user", "content": "Build a calculator", "type": "text"},
        {
            "role": "assistant", "content": (
                "### \U0001f4cb Plan\n\nplan text here\n\n"
                "```python\n# operations.py\ndef add(x, y):\n"
                "    return x + y\n```\n\n"
                "### \U0001f4c4 Documentation\ndocs"
            ),
            "type": "text", "agent": "Collaborative Workflow",
        },
    ]
    at.run()

    at.chat_input(key="chat_input").set_value(
        "review the generated code"
    )
    at.run()

    assert len(captured) == 1
    assert "[Previously generated code]" in captured[0]
    assert "def add" in captured[0], "fenced code must be carried along"


# ----------------------------------------------------------------------
# Google OAuth - public (permanent public URL) flow
# ----------------------------------------------------------------------
def _set_google_public_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv(
        "GOOGLE_REDIRECT_URI", "https://app.example.com/oauth2callback"
    )


def test_google_public_login_completes_via_poll(monkeypatch):
    """Clicking "Continue with Google" in public mode renders the consent
    link and logs the user in as soon as the flow finishes - the callback
    tab writes the profile into the server-side flow registry, and this
    tab's poll loop picks it up (mimicked here by the stubbed status).
    """
    from auth import google_oauth as go

    _set_google_public_env(monkeypatch)
    monkeypatch.setattr(go.webbrowser, "open", lambda url: False)

    calls = {"n": 0}

    def fake_status(flow_id):
        calls["n"] += 1
        if calls["n"] >= 2:
            return {
                "status": "done",
                "profile": {
                    "email": "muskan@gmail.com", "name": "Muskan",
                    "verified_email": True,
                },
            }
        return {
            "status": "running",
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?state=x",
        }

    monkeypatch.setattr(go, "get_flow_status", fake_status)

    at = _run()
    btn = next(
        (b for b in at.button if "Continue with Google" in (b.label or "")),
        None,
    )
    assert btn is not None, "Google button missing"
    btn.click()
    at.run()

    try:
        user = at.session_state["user"]
    except KeyError:
        pytest.fail("Google login failed - no user in session")
    assert user["email"] == "muskan@gmail.com"


def test_google_public_callback_completes_in_fresh_session(monkeypatch):
    """A fresh session that loads the app with ?code=...&state=... (the
    browser returned from Google after navigating away) completes the
    sign-in from the query string alone - no session state needed. This
    is how sign-in works through a permanent public URL."""
    from auth import google_oauth as go

    _set_google_public_env(monkeypatch)
    monkeypatch.setattr(go.webbrowser, "open", lambda url: False)
    monkeypatch.setattr(
        go, "_exchange_code", lambda *a, **k: {"access_token": "tok"}
    )
    monkeypatch.setattr(go, "_fetch_profile", lambda tok: {
        "email": "newbie@gmail.com", "name": "Newbie", "verified_email": True,
    })

    # A flow was started earlier (from the tab that clicked the button)
    # and its CSRF state is registered server-side.
    assert go.start_sign_in("cb-flow") is None
    state = go.get_flow_status("cb-flow")["state"]
    try:
        at = AppTest.from_file("app.py", default_timeout=60)
        at.query_params = {"code": "auth-code", "state": state}
        at.run()

        try:
            user = at.session_state["user"]
        except KeyError:
            pytest.fail("callback login failed - no user in session")
        assert user["email"] == "newbie@gmail.com"
    finally:
        go.clear_flow("cb-flow")


def test_followup_after_reopen_with_pure_code_message(monkeypatch):
    """A reopened conversation whose last assistant message is pure code
    (type=code, no explicit code field) must still carry that code into
    the follow-up."""
    import memory.memory as mem_mod

    monkeypatch.setattr(mem_mod, "save_history", lambda h: None)

    from agents.coordinator import CoordinatorAgent

    captured = []

    def fake_handle_task(self, task, progress_callback=None):
        captured.append(task)
        return {"response": "ok", "agent": "Chat Assistant"}

    monkeypatch.setattr(CoordinatorAgent, "handle_task", fake_handle_task)

    at = AppTest.from_file("app.py", default_timeout=60)
    at.session_state["user"] = {
        "id": 997, "username": "tester", "role": "admin",
    }
    at.session_state["token"] = "test-token"
    at.session_state["messages"] = [
        {"role": "user", "content": "write binary search", "type": "text"},
        {
            "role": "assistant",
            "content": "def binary_search(arr, target):\n    return -1\n",
            "type": "code", "agent": "Coding Agent",
        },
    ]
    at.run()

    at.chat_input(key="chat_input").set_value("explain the above code")
    at.run()

    assert len(captured) == 1
    assert "[Previously generated code]" in captured[0]
    assert "def binary_search" in captured[0]


def test_edit_sent_message_regenerates(monkeypatch):
    """ChatGPT-style edit: replace a sent user message and regenerate the
    assistant response from that point, keeping the earlier history."""
    import memory.memory as mem_mod

    monkeypatch.setattr(mem_mod, "save_history", lambda h: None)

    from agents.coordinator import CoordinatorAgent

    captured = []

    def fake_handle_task(self, task, progress_callback=None):
        captured.append(task)
        return {"response": "ok", "agent": "Chat Assistant"}

    monkeypatch.setattr(CoordinatorAgent, "handle_task", fake_handle_task)

    at = AppTest.from_file("app.py", default_timeout=90)
    at.session_state["user"] = {
        "id": 996, "username": "tester", "role": "admin",
    }
    at.session_state["token"] = "test-token"
    at.run()

    # Send a first message; the stub answers immediately.
    at.chat_input(key="chat_input").set_value("Write Binary Search")
    at.run()
    assert len(captured) == 1
    assert at.session_state["messages"][0]["content"] == "Write Binary Search"
    assert at.session_state["messages"][1]["role"] == "assistant"

    # Open the editor for message 0 (a user message).
    at.session_state["_edit_index"] = 0
    at.run()
    assert at.text_area(key="edit_text") is not None, "editor must render"

    # Change the message and save -> regenerates with the edited text.
    at.text_area(key="edit_text").set_value("Write Binary Search in Java")
    at.run()
    save = next(
        (b for b in at.button if "Save & regenerate" in (b.label or "")), None
    )
    assert save is not None, "Save & regenerate button missing"
    save.click()
    at.run()

    msgs = at.session_state["messages"]
    assert msgs[0]["content"] == "Write Binary Search in Java"
    assert len(msgs) == 2, "old response must be replaced, not duplicated"
    assert msgs[1]["role"] == "assistant"
    assert len(captured) == 2
    assert "Write Binary Search in Java" in captured[1]


def test_model_selector_in_settings_not_sidebar(monkeypatch):
    """The Model Selector must NOT live in the sidebar; it belongs on the
    Settings page, and the saved selection persists."""
    import memory.memory as mem_mod

    monkeypatch.setattr(mem_mod, "save_history", lambda h: None)

    from agents.coordinator import CoordinatorAgent

    def fake_handle_task(self, task, progress_callback=None):
        return {"response": "ok", "agent": "Chat Assistant"}

    monkeypatch.setattr(CoordinatorAgent, "handle_task", fake_handle_task)

    at = AppTest.from_file("app.py", default_timeout=90)
    at.session_state["user"] = {
        "id": 995, "username": "tester", "role": "admin",
    }
    at.session_state["token"] = "test-token"
    at.run()

    # Sidebar: no model selectbox (sidebar_model key must not exist).
    assert not any(s.key == "sidebar_model" for s in at.selectbox), (
        "model selector must not be in the sidebar"
    )

    # Settings page: the selector exists and works.
    at.session_state["nav_radio"] = "settings"
    at.run()
    sel = at.selectbox(key="settings_model")
    assert sel is not None, "model selector must exist on Settings"
    sel.set_value("openai/gpt-oss-20b")
    at.run()
    from config.settings import Settings
    assert Settings().model == "openai/gpt-oss-20b"
    assert Settings().model_manual is True


def test_upload_image_option_removed():
    """The Upload Image feature is fully removed: no menu entry exists and
    no image uploader can be opened."""
    at = AppTest.from_file("app.py", default_timeout=60)
    at.session_state["user"] = {
        "id": 998, "username": "tester", "role": "admin",
    }
    at.session_state["token"] = "test-token"
    at.run()
    labels = [b.label for b in at.button]
    assert not any("Upload Image" in (l or "") for l in labels), (
        "Upload Image must be removed from the + menu"
    )
    # The removed action opens no image uploader.
    at.session_state["_attach_action"] = "upload_image"
    at.run()
    for u in at.file_uploader:
        assert "image" not in (u.label or "").lower(), (
            "no image uploader may render"
        )
