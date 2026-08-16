"""AI Coding Assistant - consumer-grade Streamlit UI.

Pages: Workspace (chat), Analytics, Chat History, Settings, Profile.
This file only renders the interface. All backend logic (agents, memory,
tools, decision engine, database) is unchanged and lives elsewhere.
"""
import html as _html
import json
import os
import re
import threading
import time
import uuid

import streamlit as st

import theme
import user_files as uf

from auth import AuthService
from auth import google_oauth
from database import get_db
from config.settings import Settings, PROVIDER_MODELS, MODEL_LABELS, ENV_KEYS
from models.model_manager import LLMError
from logsys import get_logger

log = get_logger("app")
db = get_db()
settings = Settings(db)

st.set_page_config(
    page_title="AI Coding Assistant",
    page_icon="\u26a1",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ----------------------------------------------------------------------
# THEME (dark only - the app ships with a single dark design)
# ----------------------------------------------------------------------
font_size = settings.get("font_size", "md")
st.markdown(theme.theme_css("dark", font_size), unsafe_allow_html=True)

# ----------------------------------------------------------------------
# BACKEND (cached - identical pipeline as before)
# ----------------------------------------------------------------------
@st.cache_resource
def load_backend():
    from models.llm import LLM
    from tools.llm_guard import LLMGuard
    from memory.memory import Memory
    from memory.short_term_memory import ShortTermMemory
    from agents.coordinator import CoordinatorAgent

    model = LLM()
    guard = LLMGuard()
    memory = Memory()
    short_memory = ShortTermMemory()
    coordinator = CoordinatorAgent(model, guard, memory, short_memory)
    return model, guard, memory, short_memory, coordinator


auth = AuthService(db)
auth.ensure_default_admin()

# ----------------------------------------------------------------------
# GOOGLE OAUTH STARTUP DIAGNOSTICS (log only - the login UI is unchanged)
# Reports missing values, an invalid callback port, and whether Google
# Login is enabled. Never logs secrets.
# ----------------------------------------------------------------------
for _line in google_oauth.config_report():
    log.info(_line)

backend = load_backend()
model, guard, memory, short_memory, coordinator = backend

if "coordinator" not in st.session_state:
    st.session_state.coordinator = coordinator

# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------
def _esc(value) -> str:
    return _html.escape(str(value), quote=True)


CODE_PREFIXES = ("def ", "class ", "import ", "from ", "print(")


def is_code_response(text):
    t = (text or "").strip()
    return t.startswith(CODE_PREFIXES) or t.startswith(("FILE:", "PATCH:"))


def _load_messages(conv_id):
    """Convert stored DB messages into UI message dicts."""
    messages = []
    attach_map = {}
    try:
        attach_map = db.list_message_attachments(conv_id)
    except Exception:
        pass
    for row in db.list_messages(conv_id):
        content = row["content"] or ""
        mtype = "code" if is_code_response(content) else "text"
        messages.append({
            "role": row["role"], "content": content, "type": mtype,
            "agent": row.get("agent"),
            # DB row id so message editing can update/truncate in place.
            "id": row["id"],
            "attachments": attach_map.get(row["id"], []),
        })
    return messages


def _fmt_ms(ms):
    ms = int(ms or 0)
    if ms < 1000:
        return f"{ms} ms"
    return f"{ms / 1000:.1f}s"


# ----------------------------------------------------------------------
# Public shared conversations (read-only, no login required)
# ----------------------------------------------------------------------
def _render_shared_message(msg, owner_user_id):
    """Read-only rendering of one message on the public share page."""
    role = msg["role"]
    avatar = "\U0001f9d1\u200d\U0001f4bb" if role == "user" else "\u26a1"
    with st.chat_message(role, avatar=avatar):
        content = msg.get("content") or ""
        if msg.get("type") == "code" or is_code_response(content):
            st.code(content, language="python")
        else:
            st.markdown(content)
        if role == "user" and msg.get("attachments"):
            mgr = uf.UserFiles(owner_user_id)
            chips = []
            for a in msg["attachments"]:
                name = a.get("name") or ""
                chips.append(
                    f"<span class='pill info'>&#128206; {_esc(name)}</span>"
                )
            if chips:
                st.markdown(
                    '<div class="meta-bar">' + "".join(chips) + "</div>",
                    unsafe_allow_html=True,
                )


def _render_shared_page(share):
    """Public read-only conversation page (no login required)."""
    conv = db.get_conversation(share["conversation_id"])
    if not conv:
        st.markdown(theme.empty_state(
            "\U0001f6ab", "This link is no longer available",
            "The conversation may have been deleted or sharing was stopped.",
        ), unsafe_allow_html=True)
        return
    st.markdown(
        '<div class="share-banner">\U0001f517 Shared via a public link '
        "- anyone with this link can view the conversation.</div>",
        unsafe_allow_html=True,
    )
    title = (conv.get("title") or "Shared conversation").strip()
    messages = _load_messages(share["conversation_id"])
    st.markdown(
        f'<div class="page-title">{_esc(title)}</div>', unsafe_allow_html=True
    )
    st.markdown(
        f'<div class="fx-sub" style="color:var(--muted);font-size:.8rem;">'
        f"Shared by {_esc(share.get('username') or 'a user')} \u00b7 "
        f"{len(messages)} message{'s' if len(messages) != 1 else ''} \u00b7 "
        f"{time.strftime('%b %d, %Y', time.localtime())}</div>",
        unsafe_allow_html=True,
    )
    st.divider()
    if not messages:
        st.caption("_This conversation has no messages yet._")
    for m in messages:
        _render_shared_message(m, share["user_id"])


# ----------------------------------------------------------------------
# Conversation helpers (titles, grouping, export)
# ----------------------------------------------------------------------
_TITLE_VERBS = [
    "write me", "write a", "write an", "write",
    "create a", "create an", "create",
    "build a", "build an", "build",
    "make a", "make an", "make",
    "generate a", "generate an", "generate",
    "develop a", "develop an", "develop",
    "implement a", "implement an", "implement",
    "design a", "design an", "design",
    "analyze", "analyse", "review", "explain",
    "debug", "document", "fix", "optimize", "refactor",
]
_TITLE_KEEP_LOWER = {"a", "an", "the", "of", "to", "in", "on", "for", "with", "and", "or", "vs"}


def _auto_title(prompt):
    """Derive a short, meaningful conversation title from the first prompt.

    "Write Python Binary Search"      -> "Python Binary Search"
    "Build a Food Delivery App"       -> "Food Delivery App"
    "Analyze the Flask project"       -> "The Flask Project"
    """
    text = ((prompt or "").strip() or "New chat")
    first_line = text.splitlines()[0].strip().strip('\"\u2018\u2019\u201c\u201d')
    low = first_line.lower()
    for verb in _TITLE_VERBS:
        if low.startswith(verb):
            first_line = first_line[len(verb):].strip().lstrip(",:;-").strip()
            break
    # Drop a leading article that would read awkwardly.
    if first_line.lower().startswith(("a ", "an ", "the ")):
        parts = first_line.split(" ", 1)
        if len(parts) > 1:
            first_line = parts[1]
    words = first_line.split()
    if not words:
        return "New chat"
    titled = " ".join(
        w.capitalize() if (i == 0 or w.lower() not in _TITLE_KEEP_LOWER) else w.lower()
        for i, w in enumerate(words)
    )
    return titled[:46] + ("…" if len(titled) > 46 else "")


def _conversation_bucket(ts):
    """Group a conversation timestamp into Today / Yesterday / 7 days /
    30 days / Older buckets (ChatGPT-style sidebar grouping)."""
    try:
        parsed = time.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return "Older"
    then = time.mktime(parsed)
    now = time.time()
    day = 86400
    if now - then < day:
        return "Today"
    if now - then < 2 * day:
        return "Yesterday"
    if now - then < 7 * day:
        return "Previous 7 Days"
    if now - then < 30 * day:
        return "Previous 30 Days"
    return "Older"


def _conversation_markdown(conv, messages, attach_map):
    """Render a conversation as clean Markdown (for .md / .txt export)."""
    title = (conv.get("title") or "New chat").strip()
    lines = [
        f"# {title}",
        "",
        f"_Exported from AI Coding Assistant v{APP_VERSION} on "
        f"{time.strftime('%Y-%m-%d %H:%M')}_",
        "",
        f"- Created: {(conv.get('created_at') or '')[:16]}",
        f"- Messages: {len(messages)}",
        "",
        "---",
        "",
    ]
    for m in messages:
        who = "\U0001f9d1\u200d\U0001f4bb You" if m["role"] == "user" else "\u26a1 Assistant"
        lines.append(f"## {who}")
        atts = attach_map.get(m["id"], [])
        for a in atts:
            lines.append(f"\U0001f4ce Attachment: {a['name']}")
        content = m.get("content") or ""
        if is_code_response(content):
            lines.append("```python")
            lines.append(content)
            lines.append("```")
        else:
            lines.append(content)
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def _conversation_pdf(conv, messages, attach_map):
    """Render a conversation as a PDF (via reportlab, when installed).

    Returns bytes, or None if reportlab is unavailable so the UI can
    simply skip the PDF export option.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Paragraph, SimpleDocTemplate, Spacer, Preformatted,
        )
    except Exception:
        return None
    try:
        import io as _io

        title = (conv.get("title") or "New chat").strip()
        buf = _io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=18 * mm, rightMargin=18 * mm,
            topMargin=16 * mm, bottomMargin=16 * mm,
        )
        styles = getSampleStyleSheet()
        h1 = ParagraphStyle(
            "ChatTitle", parent=styles["Title"], fontSize=20, leading=24,
            spaceAfter=2,
        )
        meta = ParagraphStyle(
            "ChatMeta", parent=styles["Normal"], fontSize=8.5,
            textColor="#6b7280", spaceAfter=10,
        )
        who = ParagraphStyle(
            "Who", parent=styles["Heading2"], fontSize=12.5, leading=16,
            spaceBefore=10, spaceAfter=3,
        )
        body = ParagraphStyle(
            "Body", parent=styles["Normal"], fontSize=10, leading=14.5,
        )
        code = ParagraphStyle(
            "Code", parent=styles["Code"], fontSize=8, leading=10.5,
            backColor="#f3f0fa", borderColor="#ddd4f2", borderWidth=0.6,
            borderPadding=6, spaceBefore=4, spaceAfter=6,
        )

        story = [
            Paragraph(title, h1),
            Paragraph(
                f"Exported from AI Coding Assistant v{APP_VERSION} \u00b7 "
                f"{len(messages)} messages \u00b7 "
                f"{str(conv.get('created_at') or '')[:16]}",
                meta,
            ),
        ]
        for m in messages:
            who_txt = "You" if m["role"] == "user" else "Assistant"
            story.append(Paragraph(who_txt, who))
            atts = attach_map.get(m["id"], [])
            for a in atts:
                story.append(Paragraph(f"\U0001f4ce Attachment: {a['name']}", meta))
            content = (m.get("content") or "").strip()
            if not content:
                continue
            if is_code_response(content):
                story.append(Preformatted(content, code))
            else:
                story.append(Paragraph(content, body))
            story.append(Spacer(1, 6))
        doc.build(story)
        return buf.getvalue()
    except Exception:
        return None


def _app_base_url():
    """Best-effort origin of this deployment, for building share links.

    Returns the absolute ``scheme://host`` when the request headers expose
    it (dev server or reverse proxy), otherwise an empty string so the UI
    falls back to a relative ``?share=...`` link.
    """
    try:
        headers = st.context.headers or {}
        host = headers.get("Host") or headers.get("host")
        proto = headers.get("X-Forwarded-Proto") or headers.get(
            "x-forwarded-proto"
        )
        scheme = "https" if proto == "https" else "http"
        if host:
            return f"{scheme}://{host}"
    except Exception:
        pass
    return ""


def _share_url(token):
    base = _app_base_url()
    return f"{base}/?share={token}" if base else f"/?share={token}"


def _render_chat_menu(conv, ctx="hist"):
    """Shared three-dot menu: rename / pin / share / delete.

    Rendered inside a popover on both the Chat History page and the
    sidebar conversation rows. ``ctx`` keeps widget keys unique per
    location (the same conversation is visible in both at once).
    """
    cid = conv["id"]
    st.markdown(
        '<div class="attach-menu-title">Chat actions</div>',
        unsafe_allow_html=True,
    )
    if st.button(
        "\u270f\ufe0f Rename", key=f"{ctx}_mn_ren_{cid}",
        use_container_width=True, type="secondary",
    ):
        st.session_state["_dlg_rename"] = cid
        st.rerun()
    pin_label = "\U0001f4cc Unpin" if conv.get("pinned") else "\U0001f4cc Pin"
    if st.button(
        pin_label, key=f"{ctx}_mn_pin_{cid}",
        use_container_width=True, type="secondary",
    ):
        db.set_conversation_pinned(cid, 0 if conv.get("pinned") else 1)
        st.rerun()
    share_label = (
        "\U0001f517 Shared"
        if db.get_share_for_conversation(cid)
        else "\U0001f517 Share"
    )
    if st.button(
        share_label, key=f"{ctx}_mn_share_{cid}",
        use_container_width=True, type="secondary",
    ):
        st.session_state["_dlg_share"] = cid
        st.rerun()

    st.markdown(
        '<div class="attach-menu-title">Danger</div>', unsafe_allow_html=True
    )
    if st.button(
        "\U0001f5d1\ufe0f Delete", key=f"{ctx}_mn_del_{cid}",
        use_container_width=True, type="secondary",
    ):
        st.session_state["_dlg_delete"] = cid
        st.rerun()


def _finish_login(user, token, title="New session"):
    """Set the logged-in session and start a fresh conversation."""
    try:
        short_memory.clear()
    except Exception:
        pass
    st.session_state.user = user
    st.session_state.token = token
    st.session_state.messages = []
    st.session_state["_nav_request"] = "workspace"
    st.session_state.conversation_id = db.create_conversation(
        user["id"], title=title
    )
    # Clear any auth-flow state so the login page never renders stuck.
    for k in ("_auth_busy", "_auth_pending", "_auth_error", "_auth_notice"):
        st.session_state.pop(k, None)
    log.info("User %s logged in", user["username"])
    st.rerun()


def _finish_google_login(flow_id, profile, error=None):
    """Complete login from a Google profile (both OAuth modes).

    flow_id may be None for the public-flow callback tab, where the flow
    was already consumed and cleared by the completion itself.
    """
    if flow_id:
        google_oauth.clear_flow(flow_id)
    st.session_state.pop("_google_flow_id", None)
    if error:
        st.session_state._auth_error = error
    elif not profile:
        st.session_state._auth_error = (
            "Could not start a session. Please try again."
        )
    elif profile.get("verified_email") is False:
        st.session_state._auth_error = (
            "Please choose a verified Google account."
        )
    else:
        guser, gtok = auth.login_oauth(
            profile["email"], profile.get("name")
        )
        if gtok:
            _finish_login(guser, gtok)
        st.session_state._auth_error = (
            "Could not start a session. Please try again."
        )
    st.session_state._auth_busy = False
    st.rerun()


def _do_logout():
    try:
        auth.logout(st.session_state.get("token"))
        short_memory.clear()
    except Exception:
        pass
    for key in ("user", "token", "messages", "conversation_id",
                "_gen", "_attached", "_last_upload_fp",
                "nav_radio", "_nav_request", "_qa_pending", "_qa_mode",
                "_wf_collapsed", "_attach_action",
                "_attach_upload_reset", "_auth_view",
                "_auth_busy", "_auth_pending", "_auth_error", "_auth_notice"):
        st.session_state.pop(key, None)
    st.rerun()


def _new_conversation():
    st.session_state.messages = []
    st.session_state._attached = []
    st.session_state.pop("_qa_pending", None)
    st.session_state.pop("_qa_mode", None)
    st.session_state.pop("_wf_collapsed", None)
    st.session_state.conversation_id = db.create_conversation(
        st.session_state.user["id"], title="New chat"
    )


def _open_conversation(conv_id):
    """Load a stored conversation into the workspace and navigate there.

    Restores the full message history and re-attaches the files from the
    most recent user message so follow-ups ("review this", "explain line
    30") keep working without re-uploading.
    """
    st.session_state.conversation_id = conv_id
    st.session_state.messages = _load_messages(conv_id)
    st.session_state._attached = []
    st.session_state.pop("_qa_pending", None)
    # Re-attach the last upload so the working context survives a reload.
    for m in reversed(st.session_state.messages):
        if m.get("role") == "user" and m.get("attachments"):
            st.session_state._attached = [a["id"] for a in m["attachments"]]
            break
    st.session_state["_nav_request"] = "workspace"
    st.rerun()


# ----------------------------------------------------------------------
# Interface language (lightweight i18n for the app chrome)
# ----------------------------------------------------------------------
LANGS = ["en", "es", "fr", "de", "hi", "ar", "zh"]
LANG_NAMES = {"en": "English", "es": "Español", "fr": "Français",
              "de": "Deutsch", "hi": "हिन्दी", "ar": "العربية", "zh": "中文"}

I18N = {
    "nav.workspace": {"en": "Workspace", "es": "Espacio", "fr": "Espace", "de": "Arbeitsbereich", "hi": "कार्यक्षेत्र", "ar": "مساحة العمل", "zh": "工作区"},
    "nav.files": {"en": "My Files", "es": "Mis archivos", "fr": "Mes fichiers", "de": "Meine Dateien", "hi": "मेरी फ़ाइलें", "ar": "ملفاتي", "zh": "我的文件"},
    "nav.analytics": {"en": "Analytics", "es": "Estadísticas", "fr": "Statistiques", "de": "Analysen", "hi": "विश्लेषण", "ar": "التحليلات", "zh": "分析"},
    "nav.history": {"en": "Chat History", "es": "Historial", "fr": "Historique", "de": "Verlauf", "hi": "चैट इतिहास", "ar": "سجل المحادثات", "zh": "聊天记录"},
    "nav.settings": {"en": "Settings", "es": "Ajustes", "fr": "Paramètres", "de": "Einstellungen", "hi": "सेटिंग्स", "ar": "الإعدادات", "zh": "设置"},
    "nav.profile": {"en": "User Profile", "es": "Perfil", "fr": "Profil", "de": "Profil", "hi": "प्रोफ़ाइल", "ar": "الملف الشخصي", "zh": "个人资料"},
    "nav.logout": {"en": "Logout", "es": "Salir", "fr": "Déconnexion", "de": "Abmelden", "hi": "लॉग आउट", "ar": "تسجيل الخروج", "zh": "退出"},
    "page.workspace.title": {"en": "AI Workspace", "es": "Espacio de IA", "fr": "Espace IA", "de": "KI-Arbeitsbereich", "hi": "AI कार्यक्षेत्र", "ar": "مساحة الذكاء الاصطناعي", "zh": "AI 工作区"},
    "page.workspace.sub": {"en": "Ask anything - code, debug, document, plan and analyze.", "es": "Pregunta lo que quieras: código, depuración, documentos y más.", "fr": "Demandez tout : code, débogage, documentation et plus.", "de": "Frag alles: Code, Debugging, Doku und mehr.", "hi": "कुछ भी पूछें - कोड, डीबग, दस्तावेज़ और विश्लेषण।", "ar": "اسأل عن أي شيء - كود، تصحيح، توثيق وتحليل.", "zh": "询问任何内容——编码、调试、文档和分析。"},
    "page.analytics.title": {"en": "Analytics", "es": "Estadísticas", "fr": "Statistiques", "de": "Analysen", "hi": "विश्लेषण", "ar": "التحليلات", "zh": "分析"},
    "page.analytics.sub": {"en": "Your workspace at a glance.", "es": "Tu espacio de un vistazo.", "fr": "Votre espace en un coup d'œil.", "de": "Ihr Arbeitsbereich auf einen Blick.", "hi": "आपका कार्यक्षेत्र एक नज़र में।", "ar": "نظرة سريعة على مساحة العمل.", "zh": "工作区概览。"},
    "page.history.title": {"en": "Chat History", "es": "Historial de Chat", "fr": "Historique", "de": "Verlauf", "hi": "चैट इतिहास", "ar": "سجل المحادثات", "zh": "聊天记录"},
    "page.history.sub": {"en": "Jump back into any past conversation.", "es": "Vuelve a cualquier conversación.", "fr": "Reprenez vos conversations.", "de": "Springe zu alten Gesprächen.", "hi": "किसी भी पुरानी बातचीत पर लौटें।", "ar": "عُد إلى أي محادثة سابقة.", "zh": "回到任何历史对话。"},
    "page.settings.title": {"en": "Settings", "es": "Ajustes", "fr": "Paramètres", "de": "Einstellungen", "hi": "सेटिंग्स", "ar": "الإعدادات", "zh": "设置"},
    "page.settings.sub": {"en": "Make the assistant yours.", "es": "Personaliza tu asistente.", "fr": "Personnalisez votre assistant.", "de": "Passen Sie den Assistenten an.", "hi": "अपना सहायक बनाएं।", "ar": "خصص مساعدك.", "zh": "个性化您的助手。"},
    "page.profile.title": {"en": "Your Profile", "es": "Tu Perfil", "fr": "Votre Profil", "de": "Ihr Profil", "hi": "आपकी प्रोफ़ाइल", "ar": "ملفك الشخصي", "zh": "您的资料"},
    "page.profile.sub": {"en": "Your account at a glance.", "es": "Tu cuenta de un vistazo.", "fr": "Votre compte en bref.", "de": "Ihr Konto auf einen Blick.", "hi": "आपका खाता एक नज़र में।", "ar": "حسابك بنظرة سريعة.", "zh": "您的账户概览。"},
    "qa.build": {"en": "Build Application", "es": "Crear Aplicación", "fr": "Créer une App", "de": "App Erstellen", "hi": "एप्लिकेशन बनाएं", "ar": "إنشاء تطبيق", "zh": "构建应用"},
    "qa.chat": {"en": "Chat Assistant", "es": "Asistente de Chat", "fr": "Assistant", "de": "Chat-Assistent", "hi": "चैट सहायक", "ar": "مساعد الدردشة", "zh": "聊天助手"},
    "qa.writecode": {"en": "Write Code", "es": "Escribir Código", "fr": "Écrire du Code", "de": "Code Schreiben", "hi": "कोड लिखें", "ar": "كتابة الكود", "zh": "编写代码"},
    "qa.debug": {"en": "Debug Code", "es": "Depurar Código", "fr": "Déboguer", "de": "Debuggen", "hi": "कोड डीबग करें", "ar": "تصحيح الكود", "zh": "调试代码"},
    "qa.explain": {"en": "Explain Code", "es": "Explicar Código", "fr": "Expliquer", "de": "Erklären", "hi": "कोड समझाएं", "ar": "شرح الكود", "zh": "解释代码"},
    "qa.review": {"en": "Review Code", "es": "Revisar Código", "fr": "Réviser", "de": "Reviewen", "hi": "कोड समीक्षा करें", "ar": "مراجعة الكود", "zh": "审查代码"},
    "qa.codeanalysis": {"en": "Code Analysis", "es": "Análisis de Código", "fr": "Analyse de Code", "de": "Code-Analyse", "hi": "कोड विश्लेषण", "ar": "تحليل الكود", "zh": "代码分析"},
    "qa.analyze": {"en": "Analyze Project", "es": "Analizar Proyecto", "fr": "Analyser", "de": "Analysieren", "hi": "प्रोजेक्ट विश्लेषण करें", "ar": "تحليل المشروع", "zh": "分析项目"},
    "qa.docs": {"en": "Generate Documentation", "es": "Generar Docs", "fr": "Documenter", "de": "Doku Erstellen", "hi": "दस्तावेज़ बनाएं", "ar": "إنشاء توثيق", "zh": "生成文档"},
}


def _t(key):
    # English only - the interface is always rendered in English.
    entry = I18N.get(key, {})
    return entry.get("en", key)


# ----------------------------------------------------------------------
# Legal & help pages (Terms / Privacy / Help / Changelog)
# ----------------------------------------------------------------------
APP_VERSION = "2.1.0"

LEGAL_SUBPAGES = {"terms", "privacy", "help", "changelog"}

_TERMS_MD = """
**1. Acceptance of terms.** By accessing or using the AI Coding Assistant
application (\u201cthe Service\u201d), you agree to be bound by these Terms of
Service and by our Privacy Policy.

**2. The Service.** The Service provides AI-assisted software development
support, including code generation, debugging assistance, documentation,
planning and project analysis. Output is generated by artificial
intelligence and may occasionally be inaccurate, incomplete or unsuitable;
you are responsible for reviewing and testing any output before using it.

**3. Your account.** You are responsible for safeguarding your credentials
and for all activity that occurs under your account. Notify the operator
immediately if you suspect unauthorised use.

**4. Acceptable use.** You agree not to: upload malicious or unlawful
content; attempt to disrupt, overload or compromise the Service; or use the
Service for any purpose that violates applicable law.

**5. Your content.** You retain ownership of the content you upload and the
conversations you create. You grant the Service the limited permission
needed to store and process that content in order to operate the Service.

**6. Termination.** We may suspend or restrict access where a breach of
these terms has occurred. You may stop using the Service at any time and
may delete your data from the settings pages.

**7. Changes.** We may update these terms from time to time. Continued use
of the Service after changes are posted constitutes acceptance of the
updated terms.

**8. Contact.** Questions about these terms can be sent to
support@aicasistant.local.
"""

_PRIVACY_MD = """
**Data you provide.** Your conversations, uploaded files and preferences
are stored locally on the device where the Service runs.

**What we collect.** We store account information (username, role, and email
when provided), conversation history, uploaded files, and basic usage
metrics such as request counts and response times. These are used only to
operate the Service and to show you your own activity dashboard.

**How we use it.** Your data is used solely to run the Service and improve
its quality. We do not sell personal data, and we do not share your content
with third parties except as needed to process your requests through the
configured AI provider.

**AI processing.** When you send a message, it is sent to the AI model
provider configured for your workspace in order to generate a response.
Please avoid sending secrets or sensitive information you would not want
processed externally.

**Retention and deletion.** You can export or permanently delete your
conversations at any time from Settings. Uploaded files are removed from
your chats with the Clear attachments action. Deleted data is removed
from the local store.

**Security.** Access to the Service is protected by authentication and
sessions. Please keep your credentials safe and log out on shared devices.

**Contact.** Privacy questions can be sent to privacy@aicasistant.local.
"""

_HELP_MD = """
### Getting started
- **Ask anything** \u2014 type a request in the Workspace, for example
  \u201cBuild a Python CLI app\u201d or \u201cExplain this code\u201d.
- **+ menu** \u2014 the + button beside the message box offers one-click
  tasks for building, coding, debugging, documenting and analyzing.

### Working with files
- **Attach files** \u2014 use the **+** button next to the message box to
  attach Python, Java, C++, JavaScript, PDF, DOCX, TXT or ZIP files, then
  ask the assistant about them.
- **Stays in context** \u2014 attached files remain the working context for
  follow-ups until you clear them, so \u201creview this\u201d or
  \u201cexplain line 30\u201d work without re-uploading.

### Understanding responses
- Each response shows the **agent** that handled it, the **model** used, and
  how long it took.
- **Copy**, **Download** and **Regenerate** are available under every response.

### Managing conversations
- Find past chats in **Chat History** \u2014 search across them and jump back in.
- Use **New chat** or **Clear** in the Workspace to start fresh.
- Export or clear all history in **Settings**.

### Personalisation
- Change theme, text size and language in **Settings**.
- If a response looks wrong, hit **Regenerate** or rephrase your request.
"""

_CHANGELOG_MD = """
### v2.1 \u2014 Enterprise release
- New: Terms of Service, Privacy Policy, Help Center and release notes.
- New: search across all of your conversations and messages.
- New: attachments stay with your messages, even after a reload.
- New: export any single conversation from Chat History.
- Improved: response cards now show completion status and response stats.
- Improved: clearer progress steps while the assistant is working.

### v2.0 \u2014 Complete redesign
- New: modern purple design system with dark and light themes.
- New: Workspace with quick actions, drag & drop uploads and stop control.
- New: My Files, Analytics, Chat History, Settings and Profile pages.
- New: interface languages.
"""


def _open_subpage(name):
    st.session_state["subpage"] = name
    st.rerun()


def _close_subpage():
    st.session_state.pop("subpage", None)
    st.rerun()


def _subpage_layout(icon, title, subtitle, body_md, footer_md=""):
    st.markdown(
        theme.page_header(icon, title, subtitle), unsafe_allow_html=True
    )
    if st.button("\u2190 Back", key="sub_back", type="secondary"):
        _close_subpage()
    st.markdown('<div class="fx-card legal-body">', unsafe_allow_html=True)
    st.markdown(body_md)
    st.markdown("</div>", unsafe_allow_html=True)
    if footer_md:
        st.markdown(
            f'<div class="auth-foot">{footer_md}</div>', unsafe_allow_html=True
        )


def _render_terms():
    _subpage_layout(
        "\U0001f4dc", "Terms of Service",
        "The rules that govern your use of AI Coding Assistant.",
        _TERMS_MD, f"AI Coding Assistant &middot; v{APP_VERSION}",
    )


def _render_privacy():
    _subpage_layout(
        "\U0001f6e1\ufe0f", "Privacy Policy",
        "How we collect, use and protect your data.",
        _PRIVACY_MD, f"AI Coding Assistant &middot; v{APP_VERSION}",
    )


def _render_help():
    _subpage_layout(
        "\u2753", "Help Center",
        "Answers to the most common questions.",
        _HELP_MD,
    )


def _render_changelog():
    _subpage_layout(
        "\U0001f4c5", "What's new",
        "Release notes for every version of AI Coding Assistant.",
        _CHANGELOG_MD,
    )


def _render_legal_page(name):
    pages = {
        "terms": _render_terms,
        "privacy": _render_privacy,
        "help": _render_help,
        "changelog": _render_changelog,
    }
    pages.get(name, _render_help)()


if st.session_state.get("subpage") in LEGAL_SUBPAGES:
    _render_legal_page(st.session_state["subpage"])
    st.stop()

# ======================================================================
# PUBLIC SHARED CONVERSATIONS (read-only, no login required)
# ======================================================================
# A ?share=TOKEN link opens a clean read-only view of one conversation.
_share_token = st.query_params.get("share")
if _share_token:
    _share = db.get_share_by_token(_share_token)
    if _share:
        _render_shared_page(_share)
    else:
        st.markdown(theme.empty_state(
            "\U0001f517", "Link not found",
            "This share link is invalid or has been turned off.",
        ), unsafe_allow_html=True)
    st.stop()

# ======================================================================
# LOGIN GATE
# ======================================================================
if "user" not in st.session_state:
    st.session_state.user = None
    st.session_state.token = None

if st.session_state.user is None:
    st.markdown(theme.auth_css(), unsafe_allow_html=True)

    auth_view = st.session_state.get("_auth_view", "login")
    busy = bool(st.session_state.get("_auth_busy"))
    error = st.session_state.pop("_auth_error", None)
    notice = st.session_state.pop("_auth_notice", None)

    # ------------------------------------------------------------------
    # Public-flow Google callback (?code=...&state=...).
    #
    # When GOOGLE_REDIRECT_URI is set (deployed / permanent public URL),
    # Google redirects the browser back to the app itself. That navigation
    # may land in a brand-new Streamlit session - the tab left the app to
    # visit accounts.google.com - so the callback is handled here, before
    # any session-state-dependent logic, and is CSRF-verified by the state
    # parameter against the server-side flow registry.
    # ------------------------------------------------------------------
    if google_oauth.is_public_flow():
        _qp = st.query_params
        _cb_code = _qp.get("code") or ""
        _cb_state = _qp.get("state") or ""
        _cb_err = _qp.get("error") or ""
        if _cb_code or _cb_err:
            try:
                _cb_profile = google_oauth.complete_public_callback(
                    _cb_code, _cb_state, error=_cb_err
                )
                _cb_error_msg = None
            except google_oauth.GoogleAuthError as _exc:
                _cb_profile = None
                _cb_error_msg = str(_exc)
            # Authorization codes are single-use; drop the params so a
            # rerun never tries to exchange the same code again.
            for _k in ("code", "state", "error", "error_description"):
                if _k in _qp:
                    del _qp[_k]
            if _cb_profile:
                st.toast("Signed in with Google", icon="\u2705")
                _finish_google_login(None, _cb_profile)
            st.session_state._auth_error = (
                _cb_error_msg or "Could not start a session. Please try again."
            )
            st.session_state._auth_busy = False
            st.rerun()

    # ------------------------------------------------------------------
    # Two-phase auth: the click sets _auth_pending + _auth_busy and
    # reruns, so the card renders disabled with a "Signing you in..."
    # spinner, then THIS run performs the actual sign-in work.
    # ------------------------------------------------------------------
    pending = st.session_state.pop("_auth_pending", None)
    if pending and busy:
        if pending == "email":
            with st.spinner("Signing you in..."):
                u, tok = auth.login_by_email(
                    st.session_state.get("auth_email", ""),
                    st.session_state.get("auth_password", ""),
                )
            if tok:
                _finish_login(u, tok)
            st.session_state._auth_busy = False
            st.session_state._auth_error = (
                "Incorrect email or password. Please try again."
            )
            st.rerun()
        elif pending == "google":
            # Two modes share this polling loop:
            #  * LOCAL: the OAuth round-trip (browser consent + localhost
            #    callback server) runs on a background thread and each
            #    rerun polls the stored result.
            #  * PUBLIC (permanent public URL): Google redirects the
            #    browser back to the app with ?code=...&state=... - handled
            #    above, possibly in a fresh session. This loop waits for
            #    that completion and shows the consent link meanwhile.
            flow_id = st.session_state.get("_google_flow_id")
            if not flow_id:
                flow_id = str(uuid.uuid4())
                st.session_state["_google_flow_id"] = flow_id
                start_error = google_oauth.start_sign_in(flow_id)
                if start_error:
                    st.session_state._auth_error = start_error
                    google_oauth.clear_flow(flow_id)
                    st.session_state.pop("_google_flow_id", None)
                    st.session_state._auth_busy = False
                    st.rerun()
            status = google_oauth.get_flow_status(flow_id)
            if status["status"] == "running":
                if google_oauth.is_public_flow():
                    auth_url = status.get("auth_url")
                    if auth_url:
                        st.markdown(
                            '<div class="auth-busy" style="margin-bottom:.4rem;">'
                            "\u26a1 Google sign-in opens in a new tab. Finish it "
                            "there, then return here \u2014 you'll be signed in "
                            "automatically.</div>",
                            unsafe_allow_html=True,
                        )
                        st.link_button(
                            "\U0001f517 Open Google sign-in", url=auth_url,
                            key="btn_google_open", use_container_width=True,
                            type="secondary",
                        )
                with st.spinner("Waiting for Google sign-in..."):
                    time.sleep(1.0)
                st.session_state["_auth_pending"] = "google"
                st.session_state._auth_busy = True
                st.rerun()
            _finish_google_login(
                flow_id, status.get("profile"), error=status.get("error")
            )
        elif pending == "guest":
            guser, gtok = auth.login_guest()
            if gtok:
                _finish_login(guser, gtok, title="Guest session")
            st.session_state._auth_busy = False
            st.rerun()
        elif pending == "signup":
            r_user = st.session_state.get("auth_r_user", "")
            r_pass = st.session_state.get("auth_r_pass", "")
            r_confirm = st.session_state.get("auth_r_confirm", "")
            if len((r_pass or "")) < 6:
                st.session_state._auth_error = (
                    "Password must be at least 6 characters."
                )
            elif r_pass != r_confirm:
                st.session_state._auth_error = "Passwords do not match."
            else:
                try:
                    created = auth.register(r_user, r_pass, role="developer")
                    if created:
                        st.session_state._auth_view = "login"
                        st.session_state._auth_notice = (
                            f"Account '{r_user}' created - sign in below."
                        )
                    else:
                        st.session_state._auth_error = (
                            "That username is already taken."
                        )
                except ValueError as e:
                    st.session_state._auth_error = str(e)
            st.session_state._auth_busy = False
            st.rerun()

    # ------------------------------------------------------------------
    # Hero: logo + project name + subtitle
    # ------------------------------------------------------------------
    st.markdown(
        '<div class="auth-hero">'
        '<div class="auth-hero-logo">&#9889;</div>'
        '<div class="auth-hero-name">AI Coding Assistant</div>'
        '<div class="auth-hero-sub">Your AI engineering team \u2014 '
        "code, debug, document and plan together.</div></div>",
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # Auth card
    # ------------------------------------------------------------------
    with st.container(border=True):
        if auth_view == "login":
            st.markdown(
                '<div class="auth-card-head"><h2>Welcome back</h2>'
                "<p>Continue to your AI Workspace.</p></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="auth-card-head"><h2>Create your account</h2>'
                "<p>Join in seconds \u2014 continue to your AI Workspace.</p></div>",
                unsafe_allow_html=True,
            )

        if error:
            st.markdown(
                f'<div class="auth-error">\u26a0\ufe0f {_esc(error)}</div>',
                unsafe_allow_html=True,
            )
        if notice:
            st.markdown(
                f'<div class="auth-notice">\u2705 {_esc(notice)}</div>',
                unsafe_allow_html=True,
            )
        if busy:
            st.markdown(
                '<div class="auth-busy"><span class="spin"></span> '
                "Signing you in&hellip;</div>",
                unsafe_allow_html=True,
            )

        if auth_view == "login":
            # ---- Continue with Google (real OAuth; styled in CSS via the
            # st-key-btn_google widget-key class, no JS overlay needed) ----
            if google_oauth.is_configured():
                if st.button(
                    "Continue with Google", key="btn_google",
                    type="secondary", use_container_width=True,
                    disabled=busy,
                ):
                    st.session_state["_auth_pending"] = "google"
                    st.session_state["_auth_busy"] = True
                    st.rerun()
            else:
                st.button(
                    "Continue with Google", key="btn_google",
                    type="secondary", use_container_width=True,
                    disabled=True,
                )
                _oauth_hint = " ".join(google_oauth.validate_config()["problems"])
                if not _oauth_hint:
                    _oauth_hint = "Google sign-in is not configured."
                st.markdown(
                    f'<div class="gbtn-hint">{_esc(_oauth_hint)}</div>',
                    unsafe_allow_html=True,
                )

            st.markdown('<div class="auth-divider">OR</div>', unsafe_allow_html=True)

            # ---- Continue with email ----
            with st.form("login_form"):
                st.text_input(
                    "Email or username", key="auth_email",
                    placeholder="you@example.com",
                )
                # The password field has Streamlit's native show/hide eye.
                st.text_input(
                    "Password", key="auth_password", type="password",
                    placeholder="Enter your password",
                )
                st.checkbox("Remember me", key="auth_remember")
                submitted = st.form_submit_button(
                    "Sign in", use_container_width=True, disabled=busy
                )
                if submitted and not busy:
                    st.session_state["_auth_pending"] = "email"
                    st.session_state["_auth_busy"] = True
                    st.rerun()

            # Forgot password (outside the form - Streamlit forms only
            # accept input widgets + the submit button).
            f1, f2 = st.columns([3, 1])
            with f2:
                if st.button(
                    "Forgot password?", key="forgot_pw",
                    type="tertiary", use_container_width=True,
                ):
                    st.session_state["_auth_notice"] = (
                        "Password reset isn't available in this local build - "
                        "contact your administrator."
                    )
                    st.rerun()

            # ---- Continue as Guest ----
            st.markdown('<div class="auth-guest">', unsafe_allow_html=True)
            if st.button(
                "Continue as Guest", key="btn_guest",
                use_container_width=True, type="secondary", disabled=busy,
            ):
                st.session_state["_auth_pending"] = "guest"
                st.session_state["_auth_busy"] = True
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown(
                '<div class="auth-switch">New to AI Coding Assistant?</div>',
                unsafe_allow_html=True,
            )
            if st.button(
                "Create an account", key="to_signup",
                use_container_width=True, type="tertiary", disabled=busy,
            ):
                st.session_state["_auth_view"] = "signup"
                st.rerun()

        else:
            # ---- Sign up ----
            with st.form("register_form"):
                st.text_input(
                    "Username", key="auth_r_user", placeholder="Choose a username"
                )
                # Native show/hide eye on the password fields.
                st.text_input(
                    "Password", key="auth_r_pass", type="password",
                    placeholder="Min. 6 characters",
                )
                st.text_input(
                    "Confirm password", key="auth_r_confirm", type="password",
                    placeholder="Repeat your password",
                )
                r_submit = st.form_submit_button(
                    "Create account", use_container_width=True, disabled=busy
                )
                if r_submit and not busy:
                    st.session_state["_auth_pending"] = "signup"
                    st.session_state["_auth_busy"] = True
                    st.rerun()

            st.markdown('<div class="auth-guest">', unsafe_allow_html=True)
            if st.button(
                "Continue as Guest", key="btn_guest_signup",
                use_container_width=True, type="secondary", disabled=busy,
            ):
                st.session_state["_auth_pending"] = "guest"
                st.session_state["_auth_busy"] = True
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown(
                '<div class="auth-switch">Already have an account?</div>',
                unsafe_allow_html=True,
            )
            if st.button(
                "Sign in", key="to_login",
                use_container_width=True, type="tertiary", disabled=busy,
            ):
                st.session_state["_auth_view"] = "login"
                st.rerun()

    # ------------------------------------------------------------------
    # Footer: Privacy / Terms / Help / Version
    # ------------------------------------------------------------------
    legal_cols = st.columns(3)
    with legal_cols[0]:
        if st.button("Privacy", key="login_privacy", use_container_width=True,
                     type="tertiary"):
            _open_subpage("privacy")
    with legal_cols[1]:
        if st.button("Terms", key="login_terms", use_container_width=True,
                     type="tertiary"):
            _open_subpage("terms")
    with legal_cols[2]:
        if st.button("Help", key="login_help", use_container_width=True,
                     type="tertiary"):
            _open_subpage("help")
    st.markdown(
        f'<div class="auth-foot">AI Coding Assistant &middot; v{APP_VERSION}</div>',
        unsafe_allow_html=True,
    )
    st.stop()

user = st.session_state.user
token = st.session_state.token
role = user["role"]
user_id = user["id"]

# ======================================================================
# SIDEBAR
# ======================================================================
# The sidebar stays conversation-only: the only page-level destination
# is the Workspace itself (Chat History and My Files live inside the
# sidebar conversation rows / profile menu, not in a nav list).
NAV_ITEMS = [
    ("workspace", "\U0001f3e0", "nav.workspace"),
]

# Chat menu / profile-menu destinations that are not part of the
# conversation sidebar (opened from the profile menu at the bottom).
PROFILE_MENU_ITEMS = [
    ("profile", "\U0001f464", "nav.profile"),
    ("settings", "\u2699\ufe0f", "nav.settings"),
]


def _nav_label(key):
    for k, emoji, i18n_key in NAV_ITEMS:
        if k == key:
            return f"{emoji} {_t(i18n_key)}"
    return key


def _sidebar_chat_row(conv, pinned=False, snippet=None):
    """One ChatGPT-style conversation row in the sidebar, with a \u22ef
    management menu (rename / pin / export / delete).

    ``snippet`` (optional) replaces the time meta with a preview of the
    matched message while searching - like ChatGPT's search results.
    """
    cid = conv["id"]
    title = (conv.get("title") or "New chat").strip()
    is_active = st.session_state.get("conversation_id") == cid
    icon = "\U0001f4cc " if pinned else ""
    if snippet:
        meta = snippet
    else:
        stamp = conv.get("updated_at") or conv.get("created_at")
        meta = theme.time_ago(stamp)
    label = f"{icon}{title}\n{meta}"
    r1, r2 = st.columns([5, 0.62], gap="small")
    with r1:
        if st.button(
            label,
            key=f"side_chat_{cid}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
            help=f"Open: {title}",
        ):
            _open_conversation(cid)
    with r2:
        with st.popover("\u22ef", key=f"side_menu_{cid}", help="Chat actions"):
            _render_chat_menu(conv, ctx="side")


with st.sidebar:
    # Apply any programmatic navigation requested before the widget renders.
    if st.session_state.get("_nav_request"):
        st.session_state.nav_radio = st.session_state.pop("_nav_request")
    st.markdown(
        theme.brand_html("AI Coding Assistant", "Your AI engineering team"),
        unsafe_allow_html=True,
    )

    # New chat - always one click away.
    if st.button(
        "\u2795 New chat", key="side_new_chat",
        use_container_width=True, type="primary",
    ):
        _new_conversation()
        st.session_state["_nav_request"] = "workspace"
        st.rerun()

    # Search conversations (live filter on titles + message content).
    side_q = st.text_input(
        "Search conversations", key="side_search",
        placeholder="\U0001f50d Search conversations...",
        label_visibility="collapsed",
    )
    # ChatGPT-style live search: Streamlit's text inputs only rerun on
    # Enter, so forward each keystroke (debounced) to the widget scoped
    # to the sidebar search box - results filter as you type.
    st.markdown(
        "<script>"
        "(function(){function wire(){"
        "var box=document.querySelector('[data-testid=\"stSidebar\"] "
        "[data-testid=\"stTextInput\"] input');"
        "if(!box||box.__liveSearch){return;}box.__liveSearch=1;"
        "box.addEventListener('input',function(){"
        "clearTimeout(window.__sideSearchT);"
        "window.__sideSearchT=setTimeout(function(){"
        "box.dispatchEvent(new KeyboardEvent('keydown',"
        "{key:'Enter',code:'Enter',bubbles:true}));"
        "},220);"
        "});"
        "}wire();})();"
        "</script>",
        unsafe_allow_html=True,
    )

    # Conversation-only sidebar: the single nav item is a Home affordance
    # (Settings / Profile open from the profile menu at the bottom). Any
    # stale page value from an older session (history / files / analytics)
    # is normalized back to the workspace.
    if st.session_state.get("nav_radio") not in (
        "workspace", "settings", "profile",
    ):
        st.session_state.nav_radio = "workspace"
    # Home affordance. Rendered as a button instead of a single-option
    # radio: a radio with key="nav_radio" would keep its stored widget
    # value ("workspace") and override programmatic navigation from the
    # profile menu (Settings / Profile never opened). nav_radio is a
    # plain page-state variable now; only this button writes "workspace"
    # and only the profile menu writes "settings" / "profile".
    if st.button(
        _nav_label("workspace"), key="side_home",
        use_container_width=True, type="secondary",
    ):
        st.session_state["_nav_request"] = "workspace"
        st.rerun()

    # Conversation list: pinned on top, then recent chats grouped by age.
    # (The Model Selector lives on the Settings page - it is intentionally
    # NOT in the sidebar so the conversation stays the focus.)
    all_convs = db.list_conversations(user_id, limit=200)
    if side_q:
        # ChatGPT-style search: match conversation titles AND message
        # content, show the matched conversations with a snippet.
        q = side_q.strip().lower()
        order = []
        snippets = {}
        for c in all_convs:
            if q in (c.get("title") or "").lower():
                order.append(c["id"])
                snippets[c["id"]] = "\U0001f4ac " + (c.get("title") or "").strip()[:60]
        try:
            hits = db.search_messages(user_id, side_q, limit=30)
        except Exception:
            hits = []
        for h in hits:
            cid = h["conversation_id"]
            if cid not in snippets:
                order.append(cid)
            if cid not in snippets:
                snippet = (h.get("content") or "").replace("\n", " ").strip()[:80]
                who = "You: " if h.get("role") == "user" else "Assistant: "
                snippets[cid] = who + snippet + "\u2026"
        by_id = {c["id"]: c for c in all_convs}
        matched = [by_id[cid] for cid in order if cid in by_id]
        if not matched:
            st.markdown(
                '<div class="auth-foot" style="margin-top:6px;">'
                "No conversations match \u201c" + _esc(side_q) + "\u201d</div>",
                unsafe_allow_html=True,
            )
        else:
            # Pinned chats surface first, like ChatGPT.
            matched.sort(
                key=lambda c: (0 if c.get("pinned") else 1),
            )
            st.markdown(
                theme.side_section(f"Results ({len(matched)})"),
                unsafe_allow_html=True,
            )
            for c in matched[:40]:
                _sidebar_chat_row(
                    c, pinned=bool(c.get("pinned")), snippet=snippets.get(c["id"])
                )
    else:
        pinned = db.list_pinned_conversations(user_id)
        pinned_ids = {p["id"] for p in pinned} if pinned else set()
        if pinned:
            st.markdown(theme.side_section("Pinned"), unsafe_allow_html=True)
            for p in pinned:
                _sidebar_chat_row(p, pinned=True)

        # Pinned chats are rendered above - exclude them from the recent
        # list so a pinned conversation never gets TWO sidebar rows (that
        # crashed Streamlit with a duplicate element key).
        recent = [
            c for c in all_convs
            if c.get("msg_count", 0) > 0 and c["id"] not in pinned_ids
        ][:60]
        if recent:
            groups = {}
            for c in recent:
                groups.setdefault(
                    _conversation_bucket(
                        c.get("updated_at") or c.get("created_at")
                    ),
                    [],
                ).append(c)
            for gname in (
                "Today", "Yesterday", "Previous 7 Days",
                "Previous 30 Days", "Older",
            ):
                if gname not in groups:
                    continue
                st.markdown(theme.side_section(gname), unsafe_allow_html=True)
                for c in groups[gname]:
                    _sidebar_chat_row(c)

    # ---- ChatGPT-style profile menu (pinned to the sidebar bottom)
    username = user.get("username") or "user"
    initial = (username or "?").strip()[0].upper()
    with st.popover(
        f"{initial}  {username}",
        key="profile_menu",
        help="Account menu",
    ):
        st.markdown(
            '<div style="display:flex;align-items:center;gap:12px;'
            'padding:4px 2px 12px;border-bottom:1px solid var(--border);'
            'margin-bottom:10px;">'
            f'<div class="profile-avatar" style="width:42px;height:42px;'
            f'font-size:17px;">{_esc(initial)}</div>'
            '<div>'
            f'<div class="profile-name" style="font-size:.98rem;">{_esc(username)}</div>'
            f'<div style="color:var(--muted);font-size:.78rem;">{_esc(role)}</div>'
            "</div></div>",
            unsafe_allow_html=True,
        )
        for pkey, pemoji, pi18n in PROFILE_MENU_ITEMS:
            if st.button(
                f"{pemoji} {_t(pi18n)}", key=f"prof_{pkey}",
                use_container_width=True, type="secondary",
            ):
                st.session_state["_nav_request"] = pkey
                st.rerun()
        if st.button(
            "\u2753 Help Center", key="prof_help",
            use_container_width=True, type="secondary",
        ):
            st.session_state["subpage"] = "help"
            st.rerun()
        if st.button(
            "\U0001f4dc Terms & Privacy", key="prof_legal",
            use_container_width=True, type="secondary",
        ):
            st.session_state["subpage"] = "terms"
            st.rerun()
        if st.button(
            "\U0001f6aa Logout", key="prof_logout",
            use_container_width=True, type="secondary",
        ):
            _do_logout()
        st.markdown(
            f'<div class="auth-foot" style="margin-top:6px;">'
            f"AI Coding Assistant v{APP_VERSION}</div>",
            unsafe_allow_html=True,
        )

# ----------------------------------------------------------------------
# Page dispatch
# ----------------------------------------------------------------------
st.html(theme.copy_js(), unsafe_allow_javascript=True)

page = st.session_state.get("nav_radio", "workspace")

if page == "logout":
    _do_logout()

# ======================================================================
# CHAT MESSAGE RENDERING
# ======================================================================
WF_STAGES = ["Planner", "Coding", "Documentation"]


def _render_message(msg, index):
    role = msg["role"]
    avatar = "\U0001f9d1\u200d\U0001f4bb" if role == "user" else "\u26a1"
    with st.chat_message(role, avatar=avatar):
        mtype = msg.get("type", "text")
        if mtype == "code":
            st.code(msg["content"], language="python")
        elif mtype == "workflow":
            wf = msg.get("workflow", {})
            st.markdown(
                theme.workflow_banner(WF_STAGES, 3), unsafe_allow_html=True
            )
            # Let the user exit the workflow view back to the plain
            # workspace chat without needing a new session.
            collapsed = st.session_state.get("_wf_collapsed", set())
            if index in collapsed:
                st.caption(
                    "\u2705 Workflow finished - you're back in the chat. "
                    "Ask a follow-up below or pick a new task."
                )
            else:
                t1, t2, t3 = st.tabs(
                    ["\U0001f4cb Plan", "\U0001f4bb Code", "\U0001f4c4 Documentation"]
                )
                with t1:
                    st.markdown(wf.get("planner") or "_No plan generated._")
                with t2:
                    st.code(msg.get("code") or "", language="python")
                with t3:
                    st.markdown(
                        wf.get("documentation") or "_No documentation generated._"
                    )
                if st.button(
                    "\u2713 Done - back to chat", key=f"wf_done_{index}",
                    use_container_width=True, type="secondary",
                ):
                    collapsed.add(index)
                    st.session_state["_wf_collapsed"] = collapsed
                    st.rerun()
        else:
            st.markdown(msg["content"])

        if role == "user" and msg.get("attachments"):
            chips = [
                f"<span class='pill info'>&#128206; {_esc(a['name'])}</span>"
                for a in msg["attachments"]
            ]
            st.markdown(
                '<div class="meta-bar">' + "".join(chips) + "</div>",
                unsafe_allow_html=True,
            )

        if role == "user":
            # ChatGPT-style: edit a sent message and regenerate the
            # response from that point (history before it is preserved).
            ec1, ec2 = st.columns([1, 6], gap="small")
            with ec1:
                if st.button(
                    "\u270f\ufe0f Edit", key=f"edit_msg_{index}",
                    type="tertiary",
                    help="Edit this message and regenerate the response",
                ):
                    st.session_state["_edit_index"] = index
                    st.rerun()

        if role == "assistant":
            _render_assistant_actions(msg, index)


def _render_assistant_actions(msg, index):
    """Meta bar (agent + outcome only) + actions.

    Internal details are deliberately hidden from the user: model names,
    timing and word counts are not useful to a normal conversation and
    only make the app look like an internal dashboard. The agent name is
    kept ("Coding Agent", "Reviewer Agent"...) so users know who handled
    their request, and the status pill surfaces errors/stops.
    """
    agent = _esc(msg.get("agent") or "Assistant")
    status = msg.get("status", "success")
    status_kind = "ok" if status == "success" else ("warn" if status == "stopped" else "err")
    status_label = {"success": "Completed", "stopped": "Stopped",
                    "error": "Had an error"}.get(status, "Completed")
    st.markdown(
        '<div class="meta-bar">'
        f'<span class="meta-chip"><b>{agent}</b></span>'
        f'<span class="pill {status_kind}">{status_label}</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        st.markdown(theme.copy_button(msg["content"]), unsafe_allow_html=True)
    with c2:
        st.download_button(
            "\u2b07\ufe0f Download",
            data=msg["content"],
            file_name="assistant_response.md",
            mime="text/markdown",
            key=f"dl_{index}",
            use_container_width=True,
        )
    with c3:
        if st.button(
            "\u21bb Regenerate", key=f"reg_{index}",
            use_container_width=True, type="secondary",
        ):
            st.session_state["_regenerate"] = index
            st.rerun()

# ======================================================================
# GENERATION ENGINE (runs the coordinator in a background thread so the
# UI can show live progress and offer a Stop button)
# ======================================================================
def _start_generation(prompt, regenerate=False, msg_index=None):
    gen = {
        "phase": "running",
        "prompt": prompt,
        "progress": {"index": 0, "total": 1, "stage": ""},
        "stop": False,
        "thread": None,
        "result": None,
        "status": "success",
        "started": time.time(),
        "regenerate": regenerate,
        "msg_index": msg_index,
    }

    def worker():
        try:
            result = coordinator.handle_task(
                prompt,
                progress_callback=lambda i, t, s: gen["progress"].update(
                    {"index": i, "total": t, "stage": s}
                ),
            )
            gen["result"] = result
            gen["status"] = "success"
        except Exception as exc:
            log.exception("handle_task failed: %s", exc)
            # Friendly, specific message for known LLM failures (rate
            # limit, unavailable model, invalid key, timeout...).
            message = (
                str(exc) if isinstance(exc, LLMError)
                else "I ran into a problem while handling that request. "
                     "Please try again."
            )
            gen["result"] = {
                "response": message,
                "agent": "Assistant",
            }
            gen["status"] = "error"

    gen["thread"] = threading.Thread(target=worker, daemon=True)
    gen["thread"].start()
    st.session_state["_gen"] = gen


def _finalize_generation(gen, stopped=False):
    if not stopped and gen.get("result") is None:
        stopped = True
    duration_ms = int((time.time() - gen["started"]) * 1000)
    conv_id = st.session_state.get("conversation_id")

    if stopped:
        response = (
            "\u23f9\ufe0f **Generation stopped** \u2014 the assistant was "
            "interrupted before it could finish. Try again whenever you're ready."
        )
        msg = {
            "role": "assistant", "content": response, "type": "text",
            "agent": "Assistant", "status": "stopped",
            "duration_ms": duration_ms, "prompt": gen["prompt"],
        }
        if gen.get("regenerate") and gen.get("msg_index") is not None:
            st.session_state.messages[gen["msg_index"]] = msg
        else:
            st.session_state.messages.append(msg)
        try:
            memory.add_conversation(gen["prompt"], response)
        except Exception:
            pass
    else:
        result = gen["result"]
        response = result["response"]
        agent = result["agent"]
        status = gen["status"]

        if conv_id:
            try:
                db.log_execution(user_id, agent, status, duration_ms)
                db.add_message(conv_id, "assistant", response, agent)
                if "workflow" in result:
                    db.save_workflow(
                        user_id, gen["prompt"][:500], result["workflow"]
                    )
            except Exception as e:
                log.warning("DB logging skipped: %s", e)

        if "workflow" in result:
            msg = {
                "role": "assistant", "content": response, "type": "workflow",
                "workflow": result["workflow"], "code": result.get("code", ""),
                "agent": agent, "status": status,
                "duration_ms": duration_ms, "prompt": gen["prompt"],
            }
        elif is_code_response(response):
            msg = {
                "role": "assistant",
                "content": coordinator.clean_code_output(response),
                "type": "code", "agent": agent, "status": status,
                "duration_ms": duration_ms, "prompt": gen["prompt"],
            }
        else:
            msg = {
                "role": "assistant", "content": response, "type": "text",
                "agent": agent, "status": status,
                "duration_ms": duration_ms, "prompt": gen["prompt"],
            }

        if gen.get("regenerate") and gen.get("msg_index") is not None:
            st.session_state.messages[gen["msg_index"]] = msg
        else:
            st.session_state.messages.append(msg)

        try:
            memory.add_conversation(gen["prompt"], response)
        except Exception:
            pass

    gen["phase"] = "done"


def _render_running(gen):
    with st.chat_message("assistant", avatar="\u26a1"):
        stage = gen["progress"].get("stage") or "Working on your request..."
        idx = gen["progress"].get("index", 0)
        total = max(gen["progress"].get("total", 1), 1)
        steps_html = ""
        if total > 1:
            dots = []
            for i in range(total):
                cls = "wf-step done" if i < idx else "wf-step"
                mark = "&#10003;" if i < idx else str(i + 1)
                dots.append(f'<span class="{cls}">{mark}</span>')
            steps_html = f'<div class="wf-steps" style="margin-top:10px;">{"".join(dots)}</div>'
        st.markdown(
            '<div class="meta-bar">'
            '<span class="meta-chip"><span class="live-dot"></span> '
            f"<b>{_esc(stage)}</b></span>"
            '<span class="meta-chip"><span class="typing-dots">'
            "<span></span><span></span><span></span></span></span>"
            "</div>"
            + steps_html,
            unsafe_allow_html=True,
        )
        st.progress(min(idx / total, 1.0), text=stage)
        if st.button("\u23f9\ufe0f Stop", key="stop_gen", use_container_width=True,
                     type="secondary"):
            gen["stop"] = True

# ======================================================================
# WORKSPACE (CHAT) - ChatGPT-style composer
# ======================================================================
# The "+" button beside the message box opens the attach/action menu.
# Upload entries open an inline uploader; task entries ask the user to
# describe their own request (same flow the quick actions used).
ATTACH_ACTIONS = [
    ("upload_file", "\U0001f4c4", "Upload File"),
    ("build", "\u2699\ufe0f", "Build Application"),
    ("write_code", "\U0001f4bb", "Write Code"),
    ("debug", "\U0001f41e", "Debug"),
    ("docs", "\U0001f4c4", "Documentation"),
    ("analyze_project", "\U0001f50d", "Analyze Project"),
    ("code_analysis", "\U0001f4ca", "Code Analysis"),
    ("chat", "\U0001f4ac", "Chat Assistant"),
]

ATTACH_HINTS = {
    "build": "What would you like me to build? Describe the app you have in mind.",
    "write_code": "What code would you like me to write? Describe the task or script.",
    "debug": "What code is giving you trouble? Share it and I'll fix it.",
    "docs": "What code would you like documented? Share it and I'll write the docs.",
    "analyze_project": "Which project or folder would you like me to analyze?",
    "code_analysis": "What code should I analyze? Share it and I'll examine its structure and quality.",
    "chat": "What would you like to talk about? Ask me anything.",
}

UPLOAD_ACTIONS = ("upload_file",)


def _attach_files(prompt):
    """Inline any attached files into the prompt sent to the coordinator.

    ZIP archives are treated as uploaded projects: their file list is
    inlined as context so later follow-ups ("review this", "optimize
    the project") know what the project contains.
    """
    mgr = uf.UserFiles(user_id)
    parts = [prompt]
    for fid in st.session_state.get("_attached", []):
        rec = mgr.get(fid)
        if not rec:
            continue
        if rec["ext"] == "zip":
            info = mgr.preview_info(fid)
            entries = info.get("entries", [])
            listing = "\n".join(
                f"- {_esc(e['name'])} ({theme.human_size(e['size'])})"
                for e in entries[:200]
            )
            # Extract the archive to a per-user project folder so the
            # agents can analyze the ACTUAL project files (structure,
            # review, README) instead of only seeing the file list.
            project_root = mgr.extract_zip(fid)
            if project_root:
                parts.append(
                    f"\n\n[Attached project: {rec['name']}] "
                    f"(extracted to: {project_root})\n"
                    f"Project files:\n{listing or '(empty archive)'}"
                )
            else:
                parts.append(
                    f"\n\n[Attached project: {rec['name']}] "
                    f"(could not be extracted)\n"
                    f"Project files:\n{listing or '(empty archive)'}"
                )
        else:
            text = mgr.read_text(fid, max_chars=30000)
            if text is not None:
                parts.append(f"\n\n[Attached file: {rec['name']}]\n{text}")
            else:
                parts.append(
                    f"\n\n[Attached file: {rec['name']} (binary - not inlined)]"
                )
    return "\n".join(parts)


_CODE_FENCE_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def _code_block_from_response(content):
    """Recover generated code from a markdown assistant response.

    Conversations reopened from the database lose the explicit ``code``
    field (it is not persisted), so a follow-up would otherwise only see
    the truncated surrounding text and never the actual code. Prefer the
    longest fenced block - the real generated code wins over short usage
    examples embedded in the documentation section.
    """
    if not content:
        return None
    blocks = _CODE_FENCE_RE.findall(content)
    if blocks:
        return max(blocks, key=len).strip()
    stripped = content.strip()
    if stripped.startswith(("def ", "class ", "import ", "from ", "async def")):
        return stripped
    return None


def _build_full_prompt(prompt):
    """Assemble the coordinator prompt for a user message: attached files
    + previous assistant output (code/text) + active task mode."""
    full_prompt = _attach_files(prompt)

    # Follow-up awareness: carry the previous assistant output along so
    # follow-up requests ("review this", "optimize it", "explain line 30")
    # act on what the assistant just produced instead of losing it.
    # Generated code wins (workflow responses carry both); otherwise the
    # last plain-text response is included, bounded to keep prompts lean.
    prev_code = None
    prev_text = None
    for m in reversed(st.session_state.messages):
        if m.get("role") != "assistant":
            continue
        if prev_code is None:
            code = m.get("code") or (
                m.get("content")
                if m.get("type") == "code"
                else _code_block_from_response(m.get("content", ""))
            )
            if code:
                prev_code = code
        if (
            m.get("type") == "text"
            and prev_text is None
            and (m.get("content") or "").strip()
        ):
            prev_text = m["content"]
        if prev_code is not None and prev_text is not None:
            break
    if prev_code:
        # Cap the carried-over code so follow-up prompts stay under the
        # provider's per-minute token ceiling (Groq 8B: 6k TPM).
        full_prompt += (
            f"\n\n[Previously generated code]\n{prev_code[:3000]}"
        )
    elif prev_text:
        full_prompt += (
            "\n\n[Previous assistant response]\n" + prev_text[:1200]
        )

    # Active task mode: a Quick Action picked from the + menu stays active
    # for the whole conversation, so follow-ups keep the same intent.
    qa_mode = st.session_state.get("_qa_mode")
    if qa_mode:
        mode_label = dict(ATTACH_ACTIONS).get(qa_mode, qa_mode.replace("_", " "))
        full_prompt += (
            f"\n\n[Active task mode: {mode_label}] The user selected this "
            "task earlier in the conversation. Keep applying it to the "
            "conversation's code/project context for follow-up requests."
        )
    return full_prompt


def _apply_edit(index, text):
    """ChatGPT-style edit: replace a sent user message and regenerate the
    assistant response from that point, keeping the earlier history."""
    msgs = st.session_state.messages
    text = (text or "").strip()
    valid = (
        text
        and 0 <= index < len(msgs)
        and msgs[index].get("role") == "user"
    )
    if not valid:
        st.session_state.pop("_edit_index", None)
        st.rerun()

    # Keep the history BEFORE the edited message; drop the old response(s)
    # after it (the regenerated one will replace them).
    msgs[index]["content"] = text
    del msgs[index + 1:]
    st.session_state.messages = msgs

    # Re-attach the edited message's files so follow-up context survives.
    st.session_state._attached = [
        a["id"] for a in (msgs[index].get("attachments") or [])
    ]
    st.session_state.pop("_edit_index", None)

    # Persist: update the edited user row and delete everything after it.
    conv_id = st.session_state.get("conversation_id")
    if conv_id and msgs[index].get("id"):
        try:
            db.update_message_content(msgs[index]["id"], text)
            db.delete_messages_after(conv_id, msgs[index]["id"])
        except Exception:
            pass

    _start_generation(_build_full_prompt(text))
    st.rerun()


def _submit_prompt(prompt):
    display_prompt = prompt
    full_prompt = _build_full_prompt(prompt)

    # Snapshot the currently attached files so they stay with this message.
    attachments = []
    mgr = uf.UserFiles(user_id)
    for fid in st.session_state.get("_attached", []):
        rec = mgr.get(fid)
        if rec:
            attachments.append({"id": rec["id"], "name": rec["name"]})

    st.session_state.messages.append(
        {"role": "user", "content": display_prompt, "type": "text",
         "attachments": attachments}
    )

    conv_id = st.session_state.get("conversation_id")
    if conv_id:
        # First message of a conversation -> meaningful auto title.
        if len(st.session_state.messages) == 1:
            try:
                db.update_conversation_title(conv_id, _auto_title(display_prompt))
            except Exception:
                pass
        try:
            msg_id = db.add_message(conv_id, "user", display_prompt)
            for att in attachments:
                db.attach_message_file(msg_id, conv_id, att["id"], att["name"])
        except Exception:
            pass

    _start_generation(full_prompt)
    # Files stay attached as the working context for follow-up questions
    # ("Review this", "Explain line 30"...) until the user clears them.


def _render_composer():
    """The '+' button (docked at the chat input's left edge) opens the
    attach/action menu."""
    with st.popover("+", help="Attach a file or choose a task"):
        st.markdown(
            '<div class="attach-menu">'
            '<div class="attach-menu-title">Attach &amp; actions</div>',
            unsafe_allow_html=True,
        )
        for i in range(0, len(ATTACH_ACTIONS), 2):
            cols = st.columns(2)
            for j, col in enumerate(cols):
                idx = i + j
                if idx >= len(ATTACH_ACTIONS):
                    break
                key, emoji, label = ATTACH_ACTIONS[idx]
                with col:
                    if st.button(
                        f"{emoji} {label}",
                        key=f"attach_{key}",
                        use_container_width=True,
                        type="secondary",
                    ):
                        if key in UPLOAD_ACTIONS:
                            st.session_state["_attach_action"] = key
                            st.session_state.pop("_qa_pending", None)
                        else:
                            # The task mode stays active for the whole
                            # conversation (follow-ups keep the intent).
                            st.session_state["_qa_mode"] = key
                            st.session_state["_qa_pending"] = ATTACH_HINTS[key]
                            st.session_state.pop("_attach_action", None)
                        st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    _render_attach_upload()


def _render_attach_upload():
    """Inline upload panel shown when an upload entry is picked from +."""
    action = st.session_state.get("_attach_action")
    if action not in UPLOAD_ACTIONS:
        return

    # Reset the uploader widget between sessions so stale files are never
    # re-attached when the menu is reopened.
    if st.session_state.pop("_attach_upload_reset", False):
        try:
            del st.session_state["attach_upload"]
        except KeyError:
            pass

    label = (
        "Drop files here or click to browse \u2014 Python, Java, C++, "
        "JavaScript, PDF, DOCX, TXT, ZIP"
    )
    types = sorted(uf.ALLOWED_EXTENSIONS)

    icon = {"upload_file": "\U0001f4c4"}[action]
    st.markdown(
        f'<div class="attach-upload"><div class="attach-upload-title">'
        f"{icon} {_esc(label)}</div>",
        unsafe_allow_html=True,
    )

    uploads = st.file_uploader(
        label, type=types, accept_multiple_files=True, key="attach_upload"
    )
    if uploads:
        mgr = uf.UserFiles(user_id)
        # Prevent duplicate uploads: a file already attached to this
        # conversation (same name + size -> same library record) is
        # skipped instead of producing a second chip / duplicated
        # prompt context.
        attached = st.session_state.get("_attached") or []
        attached_set = set(attached)
        saved_ids = []
        for f in uploads:
            rec = mgr.save(f.name, f.getvalue())
            if rec and rec["id"] not in attached_set:
                saved_ids.append(rec["id"])
                attached_set.add(rec["id"])
                try:
                    coordinator.note_uploaded_file(rec["name"])
                except Exception:
                    pass
        st.session_state.pop("_attach_action", None)
        st.session_state["_attach_upload_reset"] = True
        if saved_ids:
            st.session_state["_attached"] = attached + saved_ids
            st.toast(
                f"{len(saved_ids)} file(s) attached", icon="\U0001f4ce"
            )
        else:
            st.toast(
                "That file is already attached to this chat", icon="\u2139\ufe0f"
            )
        st.rerun()

    if st.button("\u2716 Close", key="attach_close", type="tertiary"):
        st.session_state.pop("_attach_action", None)
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def _render_attached_chips():
    """ChatGPT-style attachment chips above the composer.

    Each attached file gets its own chip with a remove (\u2716) button, so
    individual attachments can be dropped before sending.
    """
    attached = st.session_state.get("_attached") or []
    if not attached:
        return
    mgr = uf.UserFiles(user_id)
    keep = []
    for fid in attached:
        rec = mgr.get(fid)
        if not rec:
            continue
        keep.append(fid)
        c1, c2 = st.columns([9, 1], gap="small")
        with c1:
            st.markdown(
                f'<div class="attach-chip">&#128206; {_esc(rec["name"])}'
                f'<span class="attach-chip-meta">'
                f"{theme.human_size(rec['size'])}</span></div>",
                unsafe_allow_html=True,
            )
        with c2:
            if st.button(
                "\u2716", key=f"chip_rm_{fid}", type="secondary",
                help=f"Remove {_esc(rec['name'])}",
            ):
                st.session_state["_attached"] = [
                    f for f in st.session_state.get("_attached") if f != fid
                ]
                st.rerun()
    # Drop any stale ids (deleted from the library meanwhile).
    st.session_state["_attached"] = keep


def render_workspace():
    st.markdown(
        theme.page_header(
            "\U0001f4ac", _t("page.workspace.title"), _t("page.workspace.sub")
        ),
        unsafe_allow_html=True,
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "_attached" not in st.session_state:
        st.session_state._attached = []

    # ---- header: current conversation + new/clear/pin buttons
    conv_id = st.session_state.get("conversation_id")
    conv = db.get_conversation(conv_id) if conv_id else None
    conv_title = (conv or {}).get("title") or "New chat"
    is_pinned = bool((conv or {}).get("pinned"))
    h_col, b_col = st.columns([3, 2.4])
    with h_col:
        st.markdown(
            f'<div style="margin:2px 0 8px;">'
            f'<span class="pill info">&#128172; {_esc(conv_title)}</span></div>',
            unsafe_allow_html=True,
        )
    with b_col:
        bb1, bb2, bb3 = st.columns(3)
        with bb1:
            if st.button("\U00002795 New chat", key="new_chat_top",
                         use_container_width=True, type="secondary"):
                _new_conversation()
                st.toast("New chat started", icon="\u2728")
                st.rerun()
        with bb2:
            if st.button("\U0001f9f9 Clear", key="clear_chat_top",
                         use_container_width=True, type="secondary"):
                _new_conversation()
                st.toast("Chat cleared", icon="\U0001f9f9")
                st.rerun()
        with bb3:
            pin_label = "\U0001f4cc Unpin" if is_pinned else "\U0001f4cc Pin"
            if st.button(pin_label, key="pin_toggle",
                         use_container_width=True, type="secondary",
                         help="Show this chat in the sidebar"):
                db.set_conversation_pinned(conv_id, 0 if is_pinned else 1)
                st.toast("Chat unpinned" if is_pinned else "Chat pinned",
                         icon="\U0001f4cc")
                st.rerun()

    gen = st.session_state.get("_gen")

    # ---- regenerate request
    regenerate_idx = st.session_state.pop("_regenerate", None)
    if (
        regenerate_idx is not None
        and (gen is None or gen["phase"] != "running")
    ):
        msgs = st.session_state.messages
        if 0 <= regenerate_idx < len(msgs):
            prompt = msgs[regenerate_idx].get("prompt")
            if not prompt:
                for m in reversed(msgs[:regenerate_idx]):
                    if m["role"] == "user":
                        prompt = m["content"]
                        break
            if prompt:
                try:
                    db.delete_last_message(conv_id, "assistant")
                except Exception:
                    pass
                _start_generation(prompt, regenerate=True, msg_index=regenerate_idx)
                st.rerun()

    # ---- render messages
    for i, msg in enumerate(st.session_state.messages):
        _render_message(msg, i)

    # ---- edit-message editor (ChatGPT-like)
    # When the user clicks Edit on a sent message, show an inline editor;
    # Save truncates the conversation at that message and regenerates.
    edit_idx = st.session_state.get("_edit_index")
    if edit_idx is not None and 0 <= edit_idx < len(st.session_state.messages):
        em = st.session_state.messages[edit_idx]
        if em.get("role") == "user":
            with st.container(border=True):
                st.markdown(
                    '<div class="attach-menu-title">\u270f\ufe0f Edit message</div>',
                    unsafe_allow_html=True,
                )
                new_text = st.text_area(
                    "Edit your message",
                    value=em.get("content", ""),
                    key="edit_text",
                    height=120,
                    label_visibility="collapsed",
                )
                e1, e2 = st.columns([1, 1], gap="small")
                with e1:
                    if st.button(
                        "Save & regenerate", key="edit_save",
                        use_container_width=True, type="primary",
                    ):
                        _apply_edit(edit_idx, new_text)
                with e2:
                    if st.button(
                        "Cancel", key="edit_cancel",
                        use_container_width=True, type="secondary",
                    ):
                        st.session_state.pop("_edit_index", None)
                        st.rerun()
        else:
            st.session_state.pop("_edit_index", None)

    # ---- welcome on a fresh chat
    qa_hint = st.session_state.get("_qa_pending")
    if not st.session_state.messages and not qa_hint:
        st.markdown(
            theme.empty_state(
                "\U0001f680",
                "What can I help you build today?",
                "Ask anything, attach a file, or pick an action from the + menu.",
            ),
            unsafe_allow_html=True,
        )

    # ---- attachment chips (current working context for follow-ups)
    _render_attached_chips()

    # ---- ask-your-question box (shown after picking a quick action)
    if qa_hint:
        st.markdown(
            f'<div class="qa-prompt">\u270d\ufe0f {_esc(qa_hint)}</div>',
            unsafe_allow_html=True,
        )

    # ---- compose toolbar (+ menu + inline uploads)
    _render_composer()

    # ---- chat input
    prompt = st.chat_input(
        "Ask anything - code, debug, document, plan...", key="chat_input"
    )

    if prompt:
        st.session_state.pop("_qa_pending", None)
        gen = st.session_state.get("_gen")
        if gen is not None and gen["phase"] == "running":
            st.toast(
                "One task at a time - let the current one finish first.",
                icon="\u23f3",
            )
        else:
            _submit_prompt(prompt)
            st.rerun()

    # ---- generation progress + polling
    gen = st.session_state.get("_gen")
    if gen is not None:
        if gen["phase"] == "running":
            _render_running(gen)
            if gen["stop"] or not gen["thread"].is_alive():
                _finalize_generation(gen, stopped=bool(gen["stop"]))
                st.rerun()
            else:
                time.sleep(0.3)
                st.rerun()
        else:
            st.session_state.pop("_gen", None)

# ======================================================================
# ANALYTICS
# ======================================================================
def _series(days, rows, key):
    by_day = {r["day"]: r for r in rows}
    return [by_day.get(d, {}).get(key, 0) for d in days]


def render_analytics():
    st.markdown(
        theme.page_header(
            "\U0001f4ca", _t("page.analytics.title"), _t("page.analytics.sub")
        ),
        unsafe_allow_html=True,
    )

    stats = db.user_dashboard_stats(user_id)
    files = uf.UserFiles(user_id).list_files()

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.markdown(
            theme.metric_card("Conversations", stats["total_conversations"],
                              "\U0001f4ac", hint="Total chats"),
            unsafe_allow_html=True,
        )
    with m2:
        st.markdown(
            theme.metric_card("Requests processed", stats["total_executions"],
                              "\U0001f504", hint="Assisted requests"),
            unsafe_allow_html=True,
        )
    with m3:
        st.markdown(
            theme.metric_card("Avg response", _fmt_ms(stats["avg_response_ms"]),
                              "\u23f1\ufe0f", hint="Average time"),
            unsafe_allow_html=True,
        )
    with m4:
        st.markdown(
            theme.metric_card("Success rate", f'{stats["success_rate"]}%',
                              "\u2705", hint="Completed requests"),
            unsafe_allow_html=True,
        )
    with m5:
        st.markdown(
            theme.metric_card("Files processed", len(files),
                              "\U0001f4c4", hint="In your library"),
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="fx-card" style="margin-top:6px;">'
        '<h4>\U0001f4c8 Usage overview</h4>'
        '<div class="fx-sub">Last 14 days</div>',
        unsafe_allow_html=True,
    )
    try:
        import pandas as pd
    except Exception:
        pd = None

    if pd is None:
        st.info("Charts are ready - they light up once pandas is installed.")
    else:
        end = pd.Timestamp.now().normalize()
        days = [
            (end - pd.Timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(13, -1, -1)
        ]
        exec_rows = db.executions_by_day(user_id, 14)
        conv_rows = db.conversations_by_day(user_id, 14)
        wf_rows = db.workflows_by_day(user_id, 14)

        df_exec = pd.DataFrame(
            {
                "day": days,
                "Requests": _series(days, exec_rows, "n"),
                "Avg response (s)": [
                    round(v / 1000, 1)
                    for v in _series(days, exec_rows, "avg_ms")
                ],
            }
        )
        df_conv = pd.DataFrame(
            {"day": days, "Chats": _series(days, conv_rows, "n")}
        )
        df_wf = pd.DataFrame(
            {"day": days, "Workflows": _series(days, wf_rows, "n")}
        )

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                '<div class="fx-card"><h4>\u2b07\ufe0f Usage trend</h4>'
                '<div class="fx-sub">Requests per day</div>',
                unsafe_allow_html=True,
            )
            st.area_chart(df_exec.set_index("day")["Requests"], height=220)
            st.markdown("</div>", unsafe_allow_html=True)
        with c2:
            st.markdown(
                '<div class="fx-card"><h4>\U0001f4ac Conversation activity</h4>'
                '<div class="fx-sub">New chats per day</div>',
                unsafe_allow_html=True,
            )
            st.bar_chart(df_conv.set_index("day")["Chats"], height=220)
            st.markdown("</div>", unsafe_allow_html=True)

        c3, c4 = st.columns(2)
        with c3:
            st.markdown(
                '<div class="fx-card"><h4>\u23f1\ufe0f Response time</h4>'
                '<div class="fx-sub">Average seconds per day</div>',
                unsafe_allow_html=True,
            )
            st.line_chart(df_exec.set_index("day")["Avg response (s)"], height=220)
            st.markdown("</div>", unsafe_allow_html=True)
        with c4:
            st.markdown(
                '<div class="fx-card"><h4>\U0001f504 Workflow success</h4>'
                '<div class="fx-sub">Completed workflows per day</div>',
                unsafe_allow_html=True,
            )
            st.bar_chart(df_wf.set_index("day")["Workflows"], height=220,
                         color="#8b5cf6")
            st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    recent = [
        c for c in db.list_conversations(user_id, limit=8)
        if c.get("msg_count", 0) > 0
    ]
    if recent:
        st.markdown(theme.side_section("Recent activity"), unsafe_allow_html=True)
        for c in recent:
            st.markdown(
                theme.side_row(
                    "\U0001f4ac",
                    (c["title"] or "New chat")[:42],
                    f'{c["msg_count"]} msgs \u00b7 {theme.time_ago(c["created_at"])}',
                ),
                unsafe_allow_html=True,
            )

# ======================================================================
# CHAT HISTORY - conversation management (ChatGPT-style)
# ======================================================================
@st.dialog("Rename conversation")
def _rename_dialog(conv_id, current_title):
    st.write("Give this conversation a clearer title.")
    new_title = st.text_input(
        "Conversation title", value=current_title or "New chat",
        key=f"rename_in_{conv_id}",
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save", key=f"rename_save_{conv_id}",
                     use_container_width=True):
            db.update_conversation_title(
                conv_id, ((new_title or "New chat").strip() or "New chat")[:60]
            )
            st.toast("Conversation renamed", icon="\u270f\ufe0f")
            st.rerun()
    with c2:
        if st.button("Cancel", key=f"rename_cancel_{conv_id}",
                     use_container_width=True, type="secondary"):
            st.rerun()


@st.dialog("Delete this conversation?")
def _delete_dialog(conv_id, title):
    st.write(
        f"**{_esc(title)}** and all of its messages will be permanently "
        "deleted. This can't be undone."
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Delete", key=f"del_yes_{conv_id}",
                     use_container_width=True):
            db.delete_conversation(conv_id)
            if st.session_state.get("conversation_id") == conv_id:
                _new_conversation()
            st.toast("Conversation deleted", icon="\U0001f5d1\ufe0f")
            st.rerun()
    with c2:
        if st.button("Cancel", key=f"del_no_{conv_id}",
                     use_container_width=True, type="secondary"):
            st.rerun()


@st.dialog("Share conversation")
def _share_dialog(conv):
    """ChatGPT-style share modal: share via link, copy, stop sharing, and
    export (PDF / Markdown / TXT) kept inside the dialog."""
    cid = conv["id"]
    title = (conv.get("title") or "New chat").strip()
    st.write(
        f"**{_esc(title)}** \u00b7 {conv.get('msg_count', 0)} messages"
    )
    share = db.get_share_for_conversation(cid)
    if not share:
        st.markdown(
            "\U0001f512 Only this conversation will be shared via a public "
            "link \u2014 nothing else in your account is visible."
        )
        if st.button(
            "\U0001f517 Share via link", key=f"share_create_{cid}",
            use_container_width=True,
        ):
            db.create_share(cid, st.session_state.user["id"])
            st.toast("Share link created", icon="\U0001f517")
            # Re-arm the dialog before the rerun so it stays open and
            # immediately shows the generated link (Copy / Preview /
            # exports / Stop sharing). Without this the modal closes as
            # soon as the share is created and the user never sees it.
            st.session_state["_dlg_share"] = cid
            st.rerun()
        return

    token = share["token"]
    url = _share_url(token)
    st.markdown(
        '<div class="share-note">\U0001f517 Anyone with the link can view '
        "this conversation, even without an account.</div>",
        unsafe_allow_html=True,
    )
    st.text_input(
        "Share link", value=url, key=f"share_link_{cid}",
        label_visibility="collapsed",
    )
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(theme.copy_button(url), unsafe_allow_html=True)
    with c2:
        st.link_button(
            "\U0001f441\ufe0f Preview", url=f"/?share={token}",
            key=f"share_open_{cid}", use_container_width=True,
        )

    st.divider()
    st.markdown("**Export conversation**")
    messages = db.list_messages(cid)
    attach_map = db.list_message_attachments(cid)
    md_data = _conversation_markdown(conv, messages, attach_map)
    e1, e2, e3 = st.columns(3)
    with e1:
        st.download_button(
            "\u2b07\ufe0f .md", data=md_data, file_name=f"chat_{cid}.md",
            mime="text/markdown", key=f"share_exp_md_{cid}",
            use_container_width=True, type="secondary",
        )
    with e2:
        pdf_data = _conversation_pdf(conv, messages, attach_map)
        if pdf_data is not None:
            st.download_button(
                "\u2b07\ufe0f .pdf", data=pdf_data,
                file_name=f"chat_{cid}.pdf", mime="application/pdf",
                key=f"share_exp_pdf_{cid}", use_container_width=True,
                type="secondary",
            )
    with e3:
        st.download_button(
            "\u2b07\ufe0f .txt", data=md_data, file_name=f"chat_{cid}.txt",
            mime="text/plain", key=f"share_exp_txt_{cid}",
            use_container_width=True, type="secondary",
        )

    st.divider()
    if st.button(
        "\u26d4 Stop sharing", key=f"share_stop_{cid}",
        use_container_width=True, type="secondary",
    ):
        db.revoke_share(cid)
        st.toast("Share link revoked", icon="\u26d4")
        # Keep the dialog open (back to the "share via link" state) so
        # the user can immediately re-share if they changed their mind.
        st.session_state["_dlg_share"] = cid
        st.rerun()


def _history_row(conv):
    """One conversation card with Open + a three-dot management menu."""
    cid = conv["id"]
    title = (conv.get("title") or "New chat").strip()
    is_active = st.session_state.get("conversation_id") == cid
    meta_parts = [
        f'{conv["msg_count"]} messages',
        theme.time_ago(conv.get("updated_at") or conv.get("created_at")),
    ]
    if conv.get("pinned"):
        meta_parts.append("\U0001f4cc pinned")
    meta_line = " \u00b7 ".join(meta_parts)
    if is_active:
        meta_line += ' &nbsp;<span class="pill info">\u25cf Current</span>'
    with st.container(border=True):
        c1, c2 = st.columns([5.4, 1.6])
        with c1:
            st.markdown(
                f'<div style="font-weight:700;font-size:.98rem;">{_esc(title)}</div>'
                f'<div class="fx-sub" style="color:var(--muted);font-size:.78rem;">'
                f"{meta_line}</div>",
                unsafe_allow_html=True,
            )
        with c2:
            o1, o2 = st.columns([1, 1])
            with o1:
                if st.button(
                    "\U0001f4ac Open", key=f"open_{cid}",
                    use_container_width=True, type="secondary",
                ):
                    _open_conversation(cid)
            with o2:
                with st.popover("\u22ef", key=f"hist_menu_{cid}",
                                help="Conversation menu"):
                    _render_chat_menu(conv, ctx="hist")


def render_chat_history():
    st.markdown(
        theme.page_header(
            "\U0001f4dc", _t("page.history.title"), _t("page.history.sub")
        ),
        unsafe_allow_html=True,
    )

    q = st.text_input(
        "Search conversations",
        placeholder="Search titles, messages, code and file names...",
        key="hist_search",
    )

    convs = [
        c for c in db.list_conversations(user_id, limit=200)
        if c.get("msg_count", 0) > 0
    ]

    if q:
        ql = q.lower()
        title_ids = {
            c["id"] for c in convs if ql in (c.get("title") or "").lower()
        }
        try:
            msg_hits = db.search_messages(user_id, q, limit=50)
        except Exception:
            msg_hits = []
        if msg_hits:
            st.markdown(
                theme.side_section("Message matches"), unsafe_allow_html=True
            )
            for r in msg_hits[:20]:
                snippet = (r["content"] or "").replace("\n", " ")[:110]
                with st.container(border=True):
                    mc1, mc2 = st.columns([5, 1])
                    with mc1:
                        st.markdown(
                            f'<div style="font-weight:650;font-size:.9rem;">'
                            f'{_esc((r["conversation_title"] or "Chat")[:42])}</div>'
                            '<div style="color:var(--muted);font-size:.8rem;">'
                            f'{"You" if r["role"] == "user" else "Assistant"} '
                            f'&middot; {_esc(snippet)}&hellip;</div>',
                            unsafe_allow_html=True,
                        )
                    with mc2:
                        if st.button(
                            "\U0001f4ac Open", key=f"msgopen_{r['message_id']}",
                            use_container_width=True, type="secondary",
                        ):
                            _open_conversation(r["conversation_id"])

        row_convs = [c for c in convs if c["id"] in title_ids]
        if not row_convs and not msg_hits:
            st.markdown(
                theme.empty_state(
                    "\U0001f50d", "No matches",
                    f"Nothing found for \u201c{q}\u201d in your conversations.",
                ),
                unsafe_allow_html=True,
            )
            return
        for conv in row_convs:
            _history_row(conv)
    else:
        if not convs:
            st.markdown(
                theme.empty_state(
                    "\U0001f4ac", "No conversations yet",
                    "Start chatting in the Workspace and your history will "
                    "appear here.",
                ),
                unsafe_allow_html=True,
            )
            return
        for conv in convs:
            _history_row(conv)

# ======================================================================
# SETTINGS (user-facing only - no keys, no internals)
# ======================================================================
def render_settings():
    st.markdown(
        theme.page_header(
            "\u2699\ufe0f", _t("page.settings.title"), _t("page.settings.sub")
        ),
        unsafe_allow_html=True,
    )

    # ---- Model (the Model Selector lives here, not in the sidebar)
    # Pick which configured LLM model handles requests. The choice is
    # persisted in Settings and applied by the LLM facade on the very
    # next call - agent routing, memory and uploaded-file context are
    # untouched. API keys stay in the environment (.env) and are never
    # rendered.
    st.markdown(
        '<div class="fx-card"><h4>\U0001f525 Model</h4>'
        '<div class="fx-sub">Choose which model answers your requests</div>',
        unsafe_allow_html=True,
    )
    provider_models = PROVIDER_MODELS.get(
        settings.provider, PROVIDER_MODELS.get("groq", [])
    )
    model_options = ["__auto__"] + list(provider_models)
    manual = settings.model_manual
    current_model = settings.model

    def _model_label(opt):
        if opt == "__auto__":
            return "Auto (per-task)"
        return MODEL_LABELS.get(opt, opt)

    sel_index = 0
    if manual and current_model in provider_models:
        sel_index = provider_models.index(current_model) + 1
    chosen = st.selectbox(
        "Model", model_options, index=sel_index,
        format_func=_model_label, key="settings_model",
    )
    if chosen == "__auto__":
        if manual:
            settings.save_model_selection(current_model, manual=False)
            st.rerun()
    elif chosen != current_model or not manual:
        settings.save_model_selection(chosen, manual=True)
        st.rerun()

    key_env = ENV_KEYS.get(settings.provider)
    key_set = bool(os.getenv(key_env)) if key_env else False
    active_label = (
        MODEL_LABELS.get(current_model, current_model)
        if manual else "Auto (per-task)"
    )
    status_label = "Ready" if key_set else "No API key configured"
    st.markdown(
        '<div style="font-size:.78rem;color:var(--muted);padding:2px 2px 10px;">'
        f"Active Model: <b>{_esc(active_label)}</b><br>"
        f"Provider: {_esc(settings.provider.capitalize())}<br>"
        f"Status: {_esc(status_label)}"
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- Appearance (dark theme + English only - no theme/language options)
    st.markdown(
        '<div class="fx-card"><h4>\U0001f3a8 Appearance</h4>'
        '<div class="fx-sub">Text size</div>',
        unsafe_allow_html=True,
    )
    size_sel = st.selectbox(
        "Text size",
        ["sm", "md", "lg", "xl"],
        index={"sm": 0, "md": 1, "lg": 2, "xl": 3}.get(
            settings.get("font_size", "md"), 1
        ),
        format_func=lambda x: {
            "sm": "Small", "md": "Medium", "lg": "Large", "xl": "Extra large",
        }[x],
    )
    if size_sel != settings.get("font_size", "md"):
        settings.set("font_size", size_sel)
        st.rerun()

    notif = st.toggle(
        "Notifications",
        value=str(settings.get("notifications", "on")).lower() != "off",
        help="Show friendly updates while the assistant works.",
    )
    settings.set("notifications", "on" if notif else "off")
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- Data
    st.markdown(
        '<div class="fx-card"><h4>\U0001f4be Data</h4>'
        '<div class="fx-sub">Export or clear your conversations</div>',
        unsafe_allow_html=True,
    )
    d1, d2 = st.columns(2)
    with d1:
        export_data = json.dumps(
            db.export_conversations(user_id), indent=2, default=str
        )
        st.download_button(
            "\u2b07\ufe0f Export conversations",
            data=export_data,
            file_name="my_conversations.json",
            mime="application/json",
            use_container_width=True,
        )
    with d2:
        if st.button("\U0001f5d1\ufe0f Clear chat history",
                     use_container_width=True, type="secondary"):
            st.session_state["_confirm_clear"] = True
    if st.session_state.pop("_confirm_clear", False):
        st.warning("This permanently deletes all of your conversations.")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Yes, clear everything", use_container_width=True):
                n = db.delete_all_conversations(user_id)
                _new_conversation()
                st.toast(f"Cleared {n} conversation(s)", icon="\U0001f5d1\ufe0f")
                st.rerun()
        with c2:
            if st.button("Cancel", use_container_width=True, type="secondary"):
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- About
    st.markdown(
        '<div class="fx-card"><h4>\U0001f3e0 About</h4>'
        '<div class="fx-sub">All about your assistant</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        theme.side_row("\U0001f916", "App", f"AI Coding Assistant v{APP_VERSION}"),
        unsafe_allow_html=True,
    )
    st.markdown(
        theme.side_row("\U0001f9e0", "Powered by", "8 specialized AI agents"),
        unsafe_allow_html=True,
    )
    st.markdown(
        theme.side_row("\U0001f510", "Account", f"{user['username']} \u00b7 {role}"),
        unsafe_allow_html=True,
    )
    # ---- Legal & help
    st.markdown(
        '<div class="fx-card"><h4>\U0001f6e1\ufe0f Legal & help</h4>'
        '<div class="fx-sub">Policies, help and release notes</div>',
        unsafe_allow_html=True,
    )
    l1, l2, l3, l4 = st.columns(4)
    with l1:
        if st.button("\U0001f4dc Terms of Service", key="set_terms",
                     use_container_width=True, type="secondary"):
            _open_subpage("terms")
    with l2:
        if st.button("\U0001f6e1\ufe0f Privacy Policy", key="set_privacy",
                     use_container_width=True, type="secondary"):
            _open_subpage("privacy")
    with l3:
        if st.button("\u2753 Help Center", key="set_help",
                     use_container_width=True, type="secondary"):
            _open_subpage("help")
    with l4:
        if st.button("\U0001f4c5 What's new", key="set_changelog",
                     use_container_width=True, type="secondary"):
            _open_subpage("changelog")
    st.markdown("</div>", unsafe_allow_html=True)

# ======================================================================
# USER PROFILE
# ======================================================================
def render_profile():
    st.markdown(
        theme.page_header(
            "\U0001f464", _t("page.profile.title"), _t("page.profile.sub")
        ),
        unsafe_allow_html=True,
    )

    full = db.get_user_by_id(user_id) or {}
    username = full.get("username") or user.get("username", "user")
    email = full.get("email") or "Not provided"
    member_since = full.get("created_at") or ""

    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown(
            f'<div class="fx-card" style="text-align:center;padding:2rem 1rem;">'
            f'<div class="avatar" style="width:84px;height:84px;font-size:2rem;'
            f'margin:0 auto 1rem;border-radius:26px;">{_esc(username[:1].upper())}</div>'
            f'<div style="font-size:1.35rem;font-weight:800;">{_esc(username)}</div>'
            f'<div style="margin-top:6px;">{theme.pill("info", role)}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )
        if st.button("\U0001f6aa Log out", use_container_width=True,
                     type="secondary"):
            _do_logout()
    with c2:
        st.markdown(
            '<div class="fx-card"><h4>\U0001f4cb Account details</h4>'
            '<div class="fx-sub">Your information</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            theme.side_row("\U0001f464", "Username", username), unsafe_allow_html=True
        )
        st.markdown(
            theme.side_row("\U0001f4e7", "Email", email), unsafe_allow_html=True
        )
        st.markdown(
            theme.side_row("\U0001f552", "Member since", str(member_since)[:10]),
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        conv_count = len(db.list_conversations(user_id, limit=1000))
        file_count = len(uf.UserFiles(user_id).list_files())
        stats = db.user_dashboard_stats(user_id)
        m1, m2, m3 = st.columns(3)
        with m1:
            st.markdown(
                theme.metric_card("Conversations", conv_count, "\U0001f4ac"),
                unsafe_allow_html=True,
            )
        with m2:
            st.markdown(
                theme.metric_card("Files", file_count, "\U0001f4c4"),
                unsafe_allow_html=True,
            )
        with m3:
            st.markdown(
                theme.metric_card("Requests", stats["total_executions"], "\U0001f504"),
                unsafe_allow_html=True,
            )


# ======================================================================
# MY FILES - per-user upload library (ChatGPT-style file management)
# ======================================================================
@st.dialog("Rename file")
def _file_rename_dialog(fid, current_name):
    st.write("Give this file a new name (keep the extension).")
    new_name = st.text_input(
        "File name", value=current_name or "", key=f"fren_in_{fid}"
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save", key=f"fren_save_{fid}", use_container_width=True):
            mgr = uf.UserFiles(user_id)
            if mgr.rename(fid, new_name.strip()):
                st.toast("File renamed", icon="\u270f\ufe0f")
            else:
                st.toast("Include the file extension", icon="\u26a0\ufe0f")
            st.rerun()
    with c2:
        if st.button("Cancel", key=f"fren_cancel_{fid}",
                     use_container_width=True, type="secondary"):
            st.rerun()


@st.dialog("Delete this file?")
def _file_delete_dialog(fid, name):
    st.write(
        f"**{_esc(name)}** will be permanently removed from your library."
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Delete", key=f"fdel_yes_{fid}", use_container_width=True):
            mgr = uf.UserFiles(user_id)
            if mgr.delete(fid):
                st.toast("File deleted", icon="\U0001f5d1\ufe0f")
            st.rerun()
    with c2:
        if st.button("Cancel", key=f"fdel_no_{fid}",
                     use_container_width=True, type="secondary"):
            st.rerun()


# Consumed after every page renders, so rename/delete work from any page.
fr = st.session_state.pop("_file_rename", None)
if fr:
    mgr = uf.UserFiles(user_id)
    rec = mgr.get(fr)
    if rec:
        _file_rename_dialog(fr, rec["name"])
fd = st.session_state.pop("_file_delete", None)
if fd:
    mgr = uf.UserFiles(user_id)
    rec = mgr.get(fd)
    if rec:
        _file_delete_dialog(fd, rec["name"])


_FILE_ICONS = {
    "py": "\U0001f40d", "js": "\U0001f4d6", "ts": "\U0001f4d6",
    "java": "\U00002618\ufe0f", "cpp": "\U0001f5c4\ufe0f", "c": "\U0001f5c4\ufe0f",
    "md": "\U0001f4c4", "txt": "\U0001f4c4", "pdf": "\U0001f4d5",
    "docx": "\U0001f4c3", "zip": "\U0001f4e6", "png": "\U0001f5bc\ufe0f",
    "jpg": "\U0001f5bc\ufe0f", "jpeg": "\U0001f5bc\ufe0f",
    "webp": "\U0001f5bc\ufe0f", "gif": "\U0001f5bc\ufe0f",
    "html": "\U0001f310", "css": "\U0001f3a8", "json": "\u2699\ufe0f",
}


def render_files():
    st.markdown(
        theme.page_header(
            "\U0001f4c1", "My Files",
            "Your private upload library - attach any file to a chat anytime.",
        ),
        unsafe_allow_html=True,
    )

    mgr = uf.UserFiles(user_id)
    q = st.text_input(
        "Search files", placeholder="\U0001f50d Search your files...",
        key="files_search", label_visibility="collapsed",
    )
    try:
        files = mgr.search(q) if q else mgr.list_files()
    except Exception:
        files = mgr.list_files()
    files.sort(key=lambda r: r.get("uploaded_at") or "", reverse=True)

    if not files:
        st.markdown(
            theme.empty_state(
                "\U0001f4c1", "No files yet",
                "Files you attach to chats land here. Upload one from the "
                "+ menu in the chat composer.",
            ),
            unsafe_allow_html=True,
        )
        return

    total = sum(r["size"] for r in files)
    st.markdown(
        f'<div class="fx-sub" style="margin-bottom:10px;">{len(files)} files '
        f"\u00b7 {theme.human_size(total)}</div>",
        unsafe_allow_html=True,
    )

    for rec in files:
        fid = rec["id"]
        name = rec["name"]
        icon = _FILE_ICONS.get(rec.get("ext", ""), "\U0001f4c4")
        meta = f'{theme.human_size(rec["size"])} \u00b7 {str(rec.get("uploaded_at") or "")[:16]}'
        with st.container(border=True):
            c1, c2 = st.columns([3.2, 3.6], gap="medium")
            with c1:
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:10px;">'
                    f'<span style="font-size:1.15rem;">{icon}</span>'
                    f'<div><div style="font-weight:700;font-size:.93rem;">'
                    f"{_esc(name)}</div>"
                    f'<div class="fx-sub" style="color:var(--muted);font-size:.76rem;">'
                    f"{meta}</div></div></div>",
                    unsafe_allow_html=True,
                )
            with c2:
                b1, b2, b3, b4 = st.columns(4, gap="small")
                with b1:
                    if st.button("\U0001f441\ufe0f", key=f"fpv_{fid}",
                                 use_container_width=True, type="secondary",
                                 help="Preview"):
                        st.session_state["_file_preview"] = fid
                        st.rerun()
                with b2:
                    data = mgr.read_bytes(fid)
                    st.download_button(
                        "\u2b07\ufe0f", data=data or b"",
                        file_name=name, mime="application/octet-stream",
                        key=f"fdl_{fid}", use_container_width=True,
                        type="secondary", help="Download",
                    )
                with b3:
                    if st.button("\u270f\ufe0f", key=f"fren_{fid}",
                                 use_container_width=True, type="secondary",
                                 help="Rename"):
                        st.session_state["_file_rename"] = fid
                        st.rerun()
                with b4:
                    if st.button("\U0001f5d1\ufe0f", key=f"fdel_{fid}",
                                 use_container_width=True, type="secondary",
                                 help="Delete"):
                        st.session_state["_file_delete"] = fid
                        st.rerun()

            if st.session_state.pop("_file_preview", None) == fid:
                info = mgr.preview_info(fid)
                if info.get("kind") == "code":
                    st.code(
                        (info.get("content") or "")[:8000],
                        language=info.get("language") or "text",
                    )
                elif info.get("kind") == "zip":
                    entries = info.get("entries") or []
                    st.markdown(
                        f"<div class='fx-sub'>{len(entries)} files inside "
                        f"{_esc(info.get('name') or '')}</div>",
                        unsafe_allow_html=True,
                    )
                    for e in entries[:60]:
                        st.markdown(
                            f"<div style='font-size:.82rem;'>"
                            f"<span style='color:var(--muted);'>&#128193;</span> "
                            f"{_esc(e['name'])} "
                            f"<span style='color:var(--muted);'>"
                            f"({theme.human_size(e['size'])})</span></div>",
                            unsafe_allow_html=True,
                        )
                    if len(entries) > 60:
                        st.markdown(
                            f"<div class='fx-sub'>... and {len(entries) - 60} more</div>",
                            unsafe_allow_html=True,
                        )
                else:
                    st.info(info.get("message") or "No preview available.")


# ======================================================================
# Conversation dialogs (rename / delete). Triggered from the sidebar
# rows OR the history page, so they are consumed here - after every
# page has rendered - and work from anywhere.
# ======================================================================
dlg_rename = st.session_state.pop("_dlg_rename", None)
if dlg_rename:
    dconv = db.get_conversation(dlg_rename)
    if dconv:
        _rename_dialog(dlg_rename, dconv.get("title") or "New chat")
dlg_delete = st.session_state.pop("_dlg_delete", None)
if dlg_delete:
    dconv = db.get_conversation(dlg_delete)
    if dconv:
        _delete_dialog(dlg_delete, dconv.get("title") or "New chat")
dlg_share = st.session_state.pop("_dlg_share", None)
if dlg_share:
    dconv = db.get_conversation(dlg_share)
    if dconv:
        _share_dialog(dconv)

# ======================================================================
# PAGE ROUTER
# ======================================================================
if page == "workspace":
    render_workspace()
elif page == "files":
    render_files()
elif page == "history":
    render_chat_history()
elif page == "settings":
    render_settings()
elif page == "profile":
    render_profile()
else:
    render_workspace()
