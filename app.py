"""AI Coding Assistant - consumer-grade Streamlit UI.

Pages: Workspace (chat), My Files, Analytics, Chat History, Settings, Profile.
This file only renders the interface. All backend logic (agents, memory,
tools, decision engine, database) is unchanged and lives elsewhere.
"""
import html as _html
import json
import os
import threading
import time

import streamlit as st

import theme
import user_files as uf

from auth import AuthService
from auth import google_oauth
from database import get_db
from config.settings import Settings
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
active_theme = "dark"
font_size = settings.get("font_size", "md")
st.markdown(theme.theme_css(active_theme, font_size), unsafe_allow_html=True)

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
            "attachments": attach_map.get(row["id"], []),
        })
    return messages


def _fmt_ms(ms):
    ms = int(ms or 0)
    if ms < 1000:
        return f"{ms} ms"
    return f"{ms / 1000:.1f}s"


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
    log.info("User %s logged in", user["username"])
    st.rerun()


def _do_logout():
    try:
        auth.logout(st.session_state.get("token"))
        short_memory.clear()
    except Exception:
        pass
    for key in ("user", "token", "messages", "conversation_id",
                "_gen", "_attached", "_last_upload_fp",
                "nav_radio", "_nav_request", "_qa_pending",
                "_wf_collapsed", "_files_processed",
                "_ws_upload_processed"):
        st.session_state.pop(key, None)
    st.rerun()


def _new_conversation():
    st.session_state.messages = []
    st.session_state._attached = []
    st.session_state.pop("_qa_pending", None)
    st.session_state.pop("_wf_collapsed", None)
    st.session_state.conversation_id = db.create_conversation(
        st.session_state.user["id"], title="New chat"
    )


# ----------------------------------------------------------------------
# Interface language (lightweight i18n for the app chrome)
# ----------------------------------------------------------------------
LANGS = ["en", "es", "fr", "de", "hi", "ar", "zh"]
LANG_NAMES = {"en": "English", "es": "Español", "fr": "Français",
              "de": "Deutsch", "hi": "हिन्दी", "ar": "العربية", "zh": "中文"}

I18N = {
    "nav.workspace": {"en": "Workspace", "es": "Espacio", "fr": "Espace", "de": "Arbeitsbereich", "hi": "कार्यक्षेत्र", "ar": "مساحة العمل", "zh": "工作区"},
    "nav.files": {"en": "My Files", "es": "Mis Archivos", "fr": "Mes Fichiers", "de": "Meine Dateien", "hi": "मेरी फ़ाइलें", "ar": "ملفاتي", "zh": "我的文件"},
    "nav.analytics": {"en": "Analytics", "es": "Estadísticas", "fr": "Statistiques", "de": "Analysen", "hi": "विश्लेषण", "ar": "التحليلات", "zh": "分析"},
    "nav.history": {"en": "Chat History", "es": "Historial", "fr": "Historique", "de": "Verlauf", "hi": "चैट इतिहास", "ar": "سجل المحادثات", "zh": "聊天记录"},
    "nav.settings": {"en": "Settings", "es": "Ajustes", "fr": "Paramètres", "de": "Einstellungen", "hi": "सेटिंग्स", "ar": "الإعدادات", "zh": "设置"},
    "nav.profile": {"en": "User Profile", "es": "Perfil", "fr": "Profil", "de": "Profil", "hi": "प्रोफ़ाइल", "ar": "الملف الشخصي", "zh": "个人资料"},
    "nav.logout": {"en": "Logout", "es": "Salir", "fr": "Déconnexion", "de": "Abmelden", "hi": "लॉग आउट", "ar": "تسجيل الخروج", "zh": "退出"},
    "page.workspace.title": {"en": "AI Workspace", "es": "Espacio de IA", "fr": "Espace IA", "de": "KI-Arbeitsbereich", "hi": "AI कार्यक्षेत्र", "ar": "مساحة الذكاء الاصطناعي", "zh": "AI 工作区"},
    "page.workspace.sub": {"en": "Ask anything - code, debug, document, plan and analyze.", "es": "Pregunta lo que quieras: código, depuración, documentos y más.", "fr": "Demandez tout : code, débogage, documentation et plus.", "de": "Frag alles: Code, Debugging, Doku und mehr.", "hi": "कुछ भी पूछें - कोड, डीबग, दस्तावेज़ और विश्लेषण।", "ar": "اسأل عن أي شيء - كود، تصحيح، توثيق وتحليل.", "zh": "询问任何内容——编码、调试、文档和分析。"},
    "page.files.title": {"en": "My Files", "es": "Mis Archivos", "fr": "Mes Fichiers", "de": "Meine Dateien", "hi": "मेरी फ़ाइलें", "ar": "ملفاتي", "zh": "我的文件"},
    "page.files.sub": {"en": "Your uploaded files, always private and ready to use.", "es": "Tus archivos subidos, siempre privados.", "fr": "Vos fichiers, toujours privés.", "de": "Ihre Dateien - immer privat.", "hi": "आपकी अपलोड की गई फ़ाइलें।", "ar": "ملفاتك المرفوعة، خاصة دائماً.", "zh": "您上传的文件，始终私密。"},
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
conversations at any time from Settings. Uploaded files can be deleted from
My Files. Deleted data is removed from the local store.

**Security.** Access to the Service is protected by authentication and
sessions. Please keep your credentials safe and log out on shared devices.

**Contact.** Privacy questions can be sent to privacy@aicasistant.local.
"""

_HELP_MD = """
### Getting started
- **Ask anything** \u2014 type a request in the Workspace, for example
  \u201cBuild a Python CLI app\u201d or \u201cExplain this code\u201d.
- **Quick actions** \u2014 one-click starters for building, debugging,
  explaining, reviewing, analyzing, documenting, testing and optimizing code.

### Working with files
- **Attach files** \u2014 drag & drop Python, Java, C++, JavaScript, PDF,
  DOCX, TXT or ZIP files into the Workspace, then ask the assistant about them.
- **My Files** \u2014 every upload lands in your private library, where you
  can preview, download, rename, search and delete it.

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
# LOGIN GATE
# ======================================================================
if "user" not in st.session_state:
    st.session_state.user = None
    st.session_state.token = None

if st.session_state.user is None:
    c_brand, c_card = st.columns([1.15, 1], gap="large")

    with c_brand:
        st.markdown(
            """
            <div class="auth-brand">
              <div class="auth-logo">&#9889;</div>
              <h1>Build software with an <span class="grad-text">AI engineering team</span></h1>
              <div class="auth-desc">
                One workspace to chat, code, debug, document and plan —
                every request is handled by the right AI agent, automatically.
              </div>
              <div class="auth-feat">
                <span class="fi">&#129504;</span>
                <div><div class="ft">Smart AI agents</div>
                <div class="fd">Coding, debugging, planning, review and documentation</div></div>
              </div>
              <div class="auth-feat">
                <span class="fi">&#128194;</span>
                <div><div class="ft">Your files, your space</div>
                <div class="fd">Upload and manage files safely, all in one place</div></div>
              </div>
              <div class="auth-feat">
                <span class="fi">&#128200;</span>
                <div><div class="ft">Clear insights</div>
                <div class="fd">Track progress and activity on a clean dashboard</div></div>
              </div>
              <div class="auth-stats">
                <div><div class="as-n">8</div><div class="as-l">AI agents</div></div>
                <div><div class="as-n">5</div><div class="as-l">Step workflow</div></div>
                <div><div class="as-n">&#8734;</div><div class="as-l">Chat history</div></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c_card:
        st.markdown(
            '<div class="auth-card-head"><h2>Welcome back</h2>'
            "<p>Sign in to your workspace.</p></div>",
            unsafe_allow_html=True,
        )

        if google_oauth.is_configured():
            if st.button("Continue with Google", use_container_width=True):
                try:
                    with st.spinner("Connecting to Google..."):
                        profile = google_oauth.sign_in_with_google()
                    if profile.get("verified_email") is False:
                        st.error("Please choose a verified Google account.")
                    else:
                        guser, gtoken = auth.login_oauth(
                            profile["email"], profile.get("name")
                        )
                        if gtoken:
                            _finish_login(guser, gtoken)
                        else:
                            st.error("Could not start a session. Please try again.")
                except Exception:
                    st.error("Google sign-in didn't complete. Please try again.")
            st.markdown(
                '<div class="auth-divider">or continue with email</div>',
                unsafe_allow_html=True,
            )

        t_in, t_up = st.tabs(["Sign in", "Create account"])
        with t_in:
            with st.form("login_form"):
                username = st.text_input("Username", placeholder="Enter your username")
                password = st.text_input(
                    "Password", type="password", placeholder="Enter your password"
                )
                submitted = st.form_submit_button("Sign in", use_container_width=True)
                if submitted:
                    user, token = auth.login(username, password)
                    if token:
                        _finish_login(user, token)
                    else:
                        st.error("Incorrect username or password.")
        with t_up:
            with st.form("register_form"):
                r_user = st.text_input("Choose a username", placeholder="e.g. alex")
                r_pass = st.text_input(
                    "Choose a password", type="password", placeholder="Min. 6 characters"
                )
                r_submit = st.form_submit_button(
                    "Create account", use_container_width=True
                )
                if r_submit:
                    try:
                        created = auth.register(r_user, r_pass, role="developer")
                        if created:
                            st.success(f"Account '{r_user}' created - sign in above.")
                        else:
                            st.error("That username is already taken.")
                    except ValueError as e:
                        st.error(str(e))

        st.divider()
        if st.button("Continue as Guest", use_container_width=True, type="secondary"):
            guser, gtoken = auth.login_guest()
            if gtoken:
                _finish_login(guser, gtoken, title="Guest session")

        legal_cols = st.columns(3)
        with legal_cols[0]:
            if st.button("Terms", key="login_terms", use_container_width=True,
                         type="tertiary"):
                _open_subpage("terms")
        with legal_cols[1]:
            if st.button("Privacy", key="login_privacy", use_container_width=True,
                         type="tertiary"):
                _open_subpage("privacy")
        with legal_cols[2]:
            if st.button("Help", key="login_help", use_container_width=True,
                         type="tertiary"):
                _open_subpage("help")
        st.markdown(
            '<div class="auth-foot">AI Coding Assistant &middot; your AI engineering team</div>',
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
NAV_ITEMS = [
    ("workspace", "\U0001f3e0", "nav.workspace"),
    ("files", "\U0001f4c2", "nav.files"),
    ("analytics", "\U0001f4ca", "nav.analytics"),
    ("history", "\U0001f4dc", "nav.history"),
    ("settings", "\u2699\ufe0f", "nav.settings"),
    ("profile", "\U0001f464", "nav.profile"),
    ("logout", "\U0001f6aa", "nav.logout"),
]


def _nav_label(key):
    for k, emoji, i18n_key in NAV_ITEMS:
        if k == key:
            return f"{emoji} {_t(i18n_key)}"
    return key


with st.sidebar:
    # Apply any programmatic navigation requested before the widget renders.
    if st.session_state.get("_nav_request"):
        st.session_state.nav_radio = st.session_state.pop("_nav_request")
    st.markdown(
        theme.brand_html("AI Coding Assistant", "Your AI engineering team"),
        unsafe_allow_html=True,
    )
    st.markdown(theme.user_chip(user["username"], role), unsafe_allow_html=True)
    st.markdown(theme.side_section("Menu"), unsafe_allow_html=True)
    st.radio(
        "Navigation",
        options=[k for k, _, _ in NAV_ITEMS],
        format_func=_nav_label,
        key="nav_radio",
        label_visibility="collapsed",
    )
    st.markdown(
        f'<div class="auth-foot">AI Coding Assistant v{APP_VERSION}</div>',
        unsafe_allow_html=True,
    )

# ----------------------------------------------------------------------
# Page dispatch
# ----------------------------------------------------------------------
st.markdown(theme.copy_js(), unsafe_allow_html=True)

page = st.session_state.get("nav_radio", "workspace")

if page == "logout":
    _do_logout()

# ======================================================================
# CHAT MESSAGE RENDERING
# ======================================================================
WF_STAGES = ["Planner", "Coding", "Reviewer", "Code Analysis", "Documentation"]


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
                theme.workflow_banner(WF_STAGES, 5), unsafe_allow_html=True
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
                t1, t2, t3, t4, t5 = st.tabs(
                    ["\U0001f4cb Plan", "\U0001f4bb Code", "\U0001f50d Review",
                     "\U0001f9ea Analysis", "\U0001f4c4 Docs"]
                )
                with t1:
                    st.markdown(wf.get("planner") or "_No plan generated._")
                with t2:
                    st.code(msg.get("code") or "", language="python")
                with t3:
                    st.markdown(wf.get("review") or "_No review generated._")
                with t4:
                    st.markdown(wf.get("code_analysis") or "_No analysis generated._")
                with t5:
                    st.markdown(wf.get("documentation") or "_No docs generated._")
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

        if role == "assistant":
            _render_assistant_actions(msg, index)


def _render_assistant_actions(msg, index):
    """Meta bar (agent, model, time, status, stats) + actions."""
    agent = _esc(msg.get("agent") or "Assistant")
    model = _esc(settings.model or "AI model")
    time_chip = ""
    if msg.get("duration_ms"):
        time_chip = (
            f'<span class="meta-chip">\u23f1\ufe0f '
            f'{_esc(_fmt_ms(msg["duration_ms"]))}</span>'
        )
    status = msg.get("status", "success")
    status_kind = "ok" if status == "success" else ("warn" if status == "stopped" else "err")
    status_label = {"success": "Completed", "stopped": "Stopped",
                    "error": "Had an error"}.get(status, "Completed")
    stats_chip = ""
    content = (msg.get("content") or "").strip()
    if content:
        stats_chip = (
            f'<span class="meta-chip">{_esc(f"{len(content.split())} words")}</span>'
        )
    st.markdown(
        '<div class="meta-bar">'
        f'<span class="meta-chip">\U0001f916 <b>{agent}</b></span>'
        f'<span class="meta-chip">\U0001f525 {model}</span>'
        f"{time_chip}"
        f'<span class="pill {status_kind}">{status_label}</span>'
        f"{stats_chip}"
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
            gen["result"] = {
                "response": (
                    "I ran into a problem while handling that request. "
                    "Please try again."
                ),
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
# WORKSPACE (CHAT)
# ======================================================================
# Quick actions: (emoji, i18n_key, hint). Clicking one does NOT run a
# canned prompt - it asks the user to describe their own task first.
QUICK_ACTIONS = [
    ("\u2699\ufe0f", "qa.build",
     "What would you like me to build? Describe the app you have in mind."),
    ("\U0001f4ac", "qa.chat",
     "What would you like to talk about? Ask me anything."),
    ("\U0001f4bb", "qa.writecode",
     "What code would you like me to write? Describe the task or script."),
    ("\U0001f41e", "qa.debug",
     "What code is giving you trouble? Share it and I'll fix it."),
    ("\U0001f4d6", "qa.explain",
     "What code would you like explained? Share it and I'll walk you through it."),
    ("\U0001f50d", "qa.review",
     "What code should I review? Share it and I'll look for issues."),
    ("\U0001f52c", "qa.codeanalysis",
     "What code should I analyze? Share it and I'll examine its structure and quality."),
    ("\U0001f4ca", "qa.analyze",
     "Which project or folder would you like me to analyze?"),
    ("\U0001f4c4", "qa.docs",
     "What code would you like documented? Share it and I'll write the docs."),
]


def _attach_files(prompt):
    """Inline any attached files into the prompt sent to the coordinator."""
    mgr = uf.UserFiles(user_id)
    parts = [prompt]
    for fid in st.session_state.get("_attached", []):
        rec = mgr.get(fid)
        if not rec:
            continue
        text = mgr.read_text(fid, max_chars=30000)
        if text is not None:
            parts.append(f"\n\n[Attached file: {rec['name']}]\n{text}")
        else:
            parts.append(f"\n\n[Attached file: {rec['name']} (binary - not inlined)]")
    return "\n".join(parts)


def _submit_prompt(prompt):
    display_prompt = prompt
    full_prompt = _attach_files(prompt)

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
        if len(st.session_state.messages) == 1:
            try:
                db.update_conversation_title(
                    conv_id, (display_prompt or "New chat")[:40]
                )
            except Exception:
                pass
        try:
            msg_id = db.add_message(conv_id, "user", display_prompt)
            for att in attachments:
                db.attach_message_file(msg_id, conv_id, att["id"], att["name"])
        except Exception:
            pass

    _start_generation(full_prompt)
    # Detach files and mark the dropzone for clearing on the NEXT run
    # (a widget key cannot be modified after it is instantiated in this
    # run, so the actual clear happens at the top of _render_upload_zone).
    st.session_state._attached = []
    st.session_state["_ws_upload_processed"] = True


def _render_quick_actions():
    labels = [(e, _t(k), p) for e, k, p in QUICK_ACTIONS]
    for row_start in range(0, len(labels), 4):
        cols = st.columns(4)
        for j, col in enumerate(cols):
            if row_start + j >= len(labels):
                break
            emoji, label, hint = labels[row_start + j]
            with col:
                if st.button(
                    f"{emoji} {label}",
                    key=f"qa_{row_start + j}",
                    use_container_width=True,
                    help="Choose this task",
                ):
                    # Ask the user for their own request instead of running
                    # a canned prompt automatically.
                    st.session_state["_qa_pending"] = hint
                    st.rerun()


def _render_upload_zone():
    st.markdown(
        '<div class="side-section">Attach files</div>', unsafe_allow_html=True
    )
    # Clear a consumed upload before the widget renders so it is never
    # re-saved or re-attached on the next rerun. Note: file_uploader
    # forbids *assigning* to its key (writes_allowed=False), so the only
    # legal reset is deleting the key before the widget is instantiated.
    if st.session_state.pop("_ws_upload_processed", False):
        try:
            del st.session_state["ws_upload"]
        except KeyError:
            pass
        st.session_state._last_upload_fp = None
    uploads = st.file_uploader(
        "Drop files here or click to browse \u2014 Python, Java, C++, "
        "JavaScript, PDF, DOCX, TXT, ZIP",
        type=sorted(uf.ALLOWED_EXTENSIONS),
        accept_multiple_files=True,
        key="ws_upload",
    )
    if uploads:
        fingerprint = tuple(sorted((f.name, f.size) for f in uploads))
        if st.session_state.get("_last_upload_fp") != fingerprint:
            mgr = uf.UserFiles(user_id)
            saved = []
            for f in uploads:
                rec = mgr.save(f.name, f.getvalue())
                saved.append(rec["id"])
            st.session_state._last_upload_fp = fingerprint
            st.session_state["_attached"] = (
                st.session_state.get("_attached") or []
            ) + saved
            st.toast(f"{len(saved)} file(s) uploaded and attached", icon="\U0001f4ce")
            st.rerun()


def _render_attached_chips():
    attached = st.session_state.get("_attached") or []
    if not attached:
        return
    mgr = uf.UserFiles(user_id)
    chips = []
    for fid in attached:
        rec = mgr.get(fid)
        if rec:
            chips.append(f"<span class='pill info'>&#128206; {_esc(rec['name'])}</span>")
    if not chips:
        return
    st.markdown(
        '<div class="meta-bar">' + "".join(chips) + "</div>",
        unsafe_allow_html=True,
    )
    if st.button("Clear attachments", key="clear_attach", type="tertiary"):
        st.session_state._attached = []
        st.rerun()


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

    # ---- header: current conversation + new/clear buttons
    conv_id = st.session_state.get("conversation_id")
    conv = db.get_conversation(conv_id) if conv_id else None
    conv_title = (conv or {}).get("title") or "New chat"
    h_col, b_col = st.columns([3, 1.6])
    with h_col:
        st.markdown(
            f'<div style="margin:2px 0 8px;">'
            f'<span class="pill info">&#128172; {_esc(conv_title)}</span></div>',
            unsafe_allow_html=True,
        )
    with b_col:
        bb1, bb2 = st.columns(2)
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

    # ---- welcome + quick actions on a fresh chat
    qa_hint = st.session_state.get("_qa_pending")
    if not st.session_state.messages and not qa_hint:
        st.markdown(
            theme.empty_state(
                "\U0001f680",
                "What can I help you build today?",
                "Ask anything, attach a file, or pick a quick action to get started.",
            ),
            unsafe_allow_html=True,
        )
        st.markdown(theme.side_section("Quick actions"), unsafe_allow_html=True)
        _render_quick_actions()

    # ---- upload zone + attachments
    _render_upload_zone()
    _render_attached_chips()

    # ---- ask-your-question box (shown after picking a quick action)
    if qa_hint:
        st.markdown(
            f'<div class="qa-prompt">\u270d\ufe0f {_esc(qa_hint)}</div>',
            unsafe_allow_html=True,
        )

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
# FILES (user uploads only - never internal project files)
# ======================================================================
def _render_preview(info):
    st.divider()
    kind = info.get("kind")
    if kind in ("code", "text"):
        st.markdown(
            f'<div class="preview-head"><span class="fx-icon">\U0001f4c4</span>'
            f"<b>{_esc(info.get('name',''))}</b></div>",
            unsafe_allow_html=True,
        )
        st.code(info.get("content") or "", language=info.get("language") or "text")
    elif kind == "zip":
        st.markdown(
            f'<div class="preview-head"><span class="fx-icon">\U0001f5dc\ufe0f</span>'
            f"<b>{_esc(info.get('name',''))}</b>"
            f'<span class="fx-hint" style="margin-left:8px;">{info.get("count",0)} entries</span></div>',
            unsafe_allow_html=True,
        )
        rows = [
            {"Entry": e["name"], "Size": theme.human_size(e["size"])}
            for e in info.get("entries", [])
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
    elif kind == "binary":
        st.info(info.get("message") or "Preview is not available for this file type.")
    else:
        st.warning(info.get("message") or "This file is no longer available.")


def _render_file_cards(files, mgr, section="all"):
    for i in range(0, len(files), 3):
        cols = st.columns(3)
        for j, col in enumerate(cols):
            idx = i + j
            if idx >= len(files):
                break
            rec = files[idx]
            icon = uf.TYPE_ICONS.get(rec["ext"], "\U0001f4c4")
            fid = rec["id"]
            with col:
                st.markdown(
                    f'<div class="file-card">'
                    f'<div class="fc-icon">{icon}</div>'
                    f'<div class="fc-name">{_esc(rec["name"])}</div>'
                    f'<div class="fc-meta">{theme.human_size(rec["size"])} \u00b7 '
                    f'{theme.time_ago(rec["uploaded_at"])}</div></div>',
                    unsafe_allow_html=True,
                )
                a1, a2, a3, a4 = st.columns(4)
                with a1:
                    if st.button("\U0001f441\ufe0f", key=f"{section}_pv_{fid}",
                                 help="Preview"):
                        st.session_state["_preview_file"] = fid
                        st.rerun()
                with a2:
                    data = mgr.read_bytes(fid)
                    if data is not None:
                        st.download_button(
                            "\u2b07\ufe0f", data=data, file_name=rec["name"],
                            key=f"{section}_dw_{fid}", help="Download",
                        )
                with a3:
                    if st.button("\u270f\ufe0f", key=f"{section}_rn_{fid}",
                                 help="Rename"):
                        st.session_state["_rename_file"] = fid
                        st.rerun()
                with a4:
                    if st.button("\U0001f5d1\ufe0f", key=f"{section}_del_{fid}",
                                 help="Delete"):
                        mgr.delete(fid)
                        if st.session_state.get("_preview_file") == fid:
                            st.session_state.pop("_preview_file", None)
                        st.toast(f"Deleted {rec['name']}", icon="\U0001f5d1\ufe0f")
                        st.rerun()

                if st.session_state.get("_rename_file") == fid:
                    new_name = st.text_input(
                        "New file name", value=rec["name"], key=f"{section}_rn_in_{fid}"
                    )
                    r1, r2 = st.columns(2)
                    with r1:
                        if st.button("Save", key=f"{section}_rn_ok_{fid}",
                                     use_container_width=True):
                            if mgr.rename(fid, new_name):
                                st.session_state.pop("_rename_file", None)
                                st.toast("File renamed", icon="\u270f\ufe0f")
                                st.rerun()
                            else:
                                st.error("Include the extension, e.g. app.py")
                    with r2:
                        if st.button("Cancel", key=f"{section}_rn_cx_{fid}",
                                     use_container_width=True, type="secondary"):
                            st.session_state.pop("_rename_file", None)
                            st.rerun()


def render_files():
    st.markdown(
        theme.page_header(
            "\U0001f4c2", _t("page.files.title"), _t("page.files.sub")
        ),
        unsafe_allow_html=True,
    )
    mgr = uf.UserFiles(user_id)

    # Clear a processed upload before the widget renders so it is never
    # re-saved on the next rerun (files used to get duplicated).
    # file_uploader forbids assigning to its key, so delete it instead.
    if st.session_state.pop("_files_processed", False):
        try:
            del st.session_state["files_upload"]
        except KeyError:
            pass

    uploaded = st.file_uploader(
        "Drop files here or click to browse",
        type=sorted(uf.ALLOWED_EXTENSIONS),
        accept_multiple_files=True,
        key="files_upload",
    )
    if uploaded:
        saved = 0
        for f in uploaded:
            rec = mgr.save(f.name, f.getvalue())
            if rec:
                saved += 1
        st.session_state["_files_processed"] = True
        st.toast(
            f"{saved} file(s) added to your library", icon="\U0001f4ce"
        )
        st.rerun()

    all_files = mgr.list_files()

    cutoff = time.strftime(
        "%Y-%m-%d", time.localtime(time.time() - 7 * 86400)
    )
    recent_count = sum(
        1 for r in all_files if str(r["uploaded_at"])[:10] >= cutoff
    )

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(theme.metric_card("Files", len(all_files), "\U0001f4c4"), unsafe_allow_html=True)
    with m2:
        st.markdown(theme.metric_card("Storage used", theme.human_size(mgr.storage_bytes()), "\U0001f4be"), unsafe_allow_html=True)
    with m3:
        st.markdown(theme.metric_card("Last 7 days", recent_count, "\U0001f552"), unsafe_allow_html=True)
    with m4:
        st.markdown(theme.metric_card("File types", len({r["ext"] for r in all_files}), "\U0001f5c2\ufe0f"), unsafe_allow_html=True)

    f1, f2 = st.columns([2, 1])
    with f1:
        q = st.text_input("Search your files...", placeholder="Type a file name", key="file_search")
    with f2:
        ext_options = sorted({r["ext"] for r in all_files})
        selected_exts = st.multiselect("Filter by type", ext_options, key="file_filter")

    results = mgr.search(q, selected_exts or None)

    recent = all_files[:5]
    if recent:
        st.markdown(theme.side_section("Recent files"), unsafe_allow_html=True)
        _render_file_cards(recent, mgr, section="recent")

    st.markdown(theme.side_section("All files"), unsafe_allow_html=True)
    if results:
        _render_file_cards(results, mgr, section="all")
    else:
        st.markdown(
            theme.empty_state(
                "\U0001f4c1", "No files yet",
                "Upload a file above and it will appear in your library.",
            ),
            unsafe_allow_html=True,
        )

    preview_id = st.session_state.get("_preview_file")
    if preview_id:
        info = mgr.preview_info(preview_id)
        _render_preview(info)

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
# CHAT HISTORY
# ======================================================================
def render_chat_history():
    st.markdown(
        theme.page_header(
            "\U0001f4dc", _t("page.history.title"), _t("page.history.sub")
        ),
        unsafe_allow_html=True,
    )

    q = st.text_input(
        "Search chats...", placeholder="Search titles and messages",
        key="hist_search",
    )
    convs = [
        c for c in db.list_conversations(user_id, limit=100)
        if c.get("msg_count", 0) > 0
    ]
    if q:
        convs = [c for c in convs if q.lower() in (c["title"] or "").lower()]

        # Also search inside messages for a deeper, more useful result set.
        try:
            msg_hits = db.search_messages(user_id, q, limit=25)
        except Exception:
            msg_hits = []
        if msg_hits:
            st.markdown(
                theme.side_section("Message matches"), unsafe_allow_html=True
            )
            for r in msg_hits:
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
                            st.session_state.conversation_id = r["conversation_id"]
                            st.session_state.messages = _load_messages(
                                r["conversation_id"]
                            )
                            st.session_state["_nav_request"] = "workspace"
                            st.rerun()

    if not convs and not q:
        st.markdown(
            theme.empty_state(
                "\U0001f4ac", "No conversations yet",
                "Start chatting in the Workspace and your history will appear here.",
            ),
            unsafe_allow_html=True,
        )
        return

    for conv in convs:
        title = (conv["title"] or "New chat").strip()
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([5, 1, 1, 1])
            with c1:
                st.markdown(
                    f'<div style="font-weight:700;font-size:.98rem;">{_esc(title)}</div>'
                    f'<div class="fx-sub" style="color:var(--muted);font-size:.78rem;">'
                    f'{conv["msg_count"]} messages \u00b7 '
                    f'{theme.time_ago(conv["created_at"])}</div>',
                    unsafe_allow_html=True,
                )
            with c2:
                if st.button("\U0001f4ac Open", key=f"open_{conv['id']}",
                             use_container_width=True, type="secondary"):
                    st.session_state.conversation_id = conv["id"]
                    st.session_state.messages = _load_messages(conv["id"])
                    st.session_state["_nav_request"] = "workspace"
                    st.rerun()
            with c3:
                export_data = json.dumps(
                    {
                        "conversation_id": conv["id"],
                        "title": title,
                        "created_at": conv["created_at"],
                        "messages": db.list_messages(conv["id"]),
                    },
                    indent=2, default=str,
                )
                st.download_button(
                    "\u2b07\ufe0f", data=export_data,
                    file_name=f"chat_{conv['id']}.json",
                    mime="application/json", key=f"exp_{conv['id']}",
                    help="Export this chat",
                )
            with c4:
                if st.button("\U0001f5d1\ufe0f", key=f"del_hist_{conv['id']}",
                             help="Delete this chat"):
                    db.delete_conversation(conv["id"])
                    if st.session_state.get("conversation_id") == conv["id"]:
                        _new_conversation()
                    st.toast("Chat deleted", icon="\U0001f5d1\ufe0f")
                    st.rerun()

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
# PAGE ROUTER
# ======================================================================
if page == "workspace":
    render_workspace()
elif page == "files":
    render_files()
elif page == "analytics":
    render_analytics()
elif page == "history":
    render_chat_history()
elif page == "settings":
    render_settings()
elif page == "profile":
    render_profile()
else:
    render_workspace()
