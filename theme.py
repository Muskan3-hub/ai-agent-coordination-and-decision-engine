"""Design system for the AI Coding Assistant UI.

Modern, consumer-grade look: deep purple-accented dark theme (plus a light
theme), rounded cards, soft shadows, smooth animations and clean typography.
All presentation lives here — backend/agent logic never touches this file.
"""
import html as _html

# ----------------------------------------------------------------------
# Utilities
# ----------------------------------------------------------------------

def _esc(value) -> str:
    """Escape dynamic values before injecting them into unsafe HTML."""
    return _html.escape(str(value), quote=True)


def human_size(num) -> str:
    try:
        num = int(num)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def time_ago(ts) -> str:
    """Friendly relative time for an ISO-like timestamp."""
    try:
        import time as _time
        parsed = _time.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")
        then = _time.mktime(parsed)
        diff = _time.time() - then
        if diff < 60:
            return "just now"
        if diff < 3600:
            return f"{int(diff // 60)}m ago"
        if diff < 86400:
            return f"{int(diff // 3600)}h ago"
        if diff < 86400 * 7:
            return f"{int(diff // 86400)}d ago"
        return str(ts)[:10]
    except (ValueError, TypeError):
        return str(ts)[:10]


# ----------------------------------------------------------------------
# Theme variables
# ----------------------------------------------------------------------

_DARK_VARS = """
:root {
    --bg: #08070d; --bg2: #0d0b16;
    --surface: #131120; --surface2: #191626; --surface3: #211d33;
    --border: rgba(196,181,253,.10); --border-strong: rgba(196,181,253,.22);
    --text: #f4f2fb; --muted: #9d96b8;
    --accent: #8b5cf6; --accent2: #a855f7; --accent3: #6366f1;
    --accent-soft: rgba(139,92,246,.16);
    --success: #34d399; --warn: #fbbf24; --danger: #fb7185;
    --shadow: 0 14px 44px rgba(2,0,14,.55);
    --shadow-soft: 0 6px 22px rgba(2,0,14,.38);
    --grad: linear-gradient(135deg, #7c3aed 0%, #a855f7 55%, #c084fc 100%);
    --glow: 0 0 0 1px rgba(168,85,247,.35), 0 8px 30px rgba(124,58,237,.35);
}
[data-testid="stAppViewContainer"] {
    background:
        radial-gradient(1100px 600px at 8% -12%, rgba(124,58,237,.20), transparent 60%),
        radial-gradient(900px 560px at 108% 4%, rgba(168,85,247,.14), transparent 55%),
        radial-gradient(800px 600px at 50% 118%, rgba(99,102,241,.08), transparent 60%),
        linear-gradient(180deg, var(--bg) 0%, var(--bg2) 100%);
    background-attachment: fixed;
    color: var(--text);
}
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, rgba(14,12,24,.96), rgba(10,9,18,.96));
    border-right: 1px solid var(--border);
    backdrop-filter: blur(10px);
}
"""

_LIGHT_VARS = """
:root {
    --bg: #f6f5fb; --bg2: #efedf8;
    --surface: #ffffff; --surface2: #f5f3fb; --surface3: #edeaf6;
    --border: rgba(76,29,149,.12); --border-strong: rgba(76,29,149,.22);
    --text: #17122b; --muted: #6d6691;
    --accent: #7c3aed; --accent2: #a855f7; --accent3: #6366f1;
    --accent-soft: rgba(139,92,246,.12);
    --success: #059669; --warn: #d97706; --danger: #e11d48;
    --shadow: 0 14px 40px rgba(76,29,149,.12);
    --shadow-soft: 0 6px 20px rgba(76,29,149,.08);
    --grad: linear-gradient(135deg, #7c3aed 0%, #a855f7 55%, #c084fc 100%);
    --glow: 0 0 0 1px rgba(168,85,247,.25), 0 8px 26px rgba(124,58,237,.18);
}
[data-testid="stAppViewContainer"] {
    background:
        radial-gradient(1100px 600px at 8% -12%, rgba(124,58,237,.12), transparent 60%),
        radial-gradient(900px 560px at 108% 4%, rgba(168,85,247,.10), transparent 55%),
        linear-gradient(180deg, var(--bg) 0%, var(--bg2) 100%);
    background-attachment: fixed;
    color: var(--text);
}
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, rgba(255,255,255,.97), rgba(248,246,253,.97));
    border-right: 1px solid var(--border);
}
"""

_BASE_CSS = """
html, body, .stApp, p, li, div, label, span, h1, h2, h3, h4, h5, h6,
input, textarea, button, select, [class*="css"] {
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI",
                 Roboto, "Helvetica Neue", Arial, sans-serif;
    color: var(--text);
}
h1, h2, h3, h4 { font-weight: 760; letter-spacing: -0.02em; }
p, li { line-height: 1.65; }
code, pre, [data-testid="stCodeBlock"] * {
    font-family: "SFMono-Regular", "JetBrains Mono", Consolas, monospace;
}
a { color: var(--accent2); text-decoration: none; }
a:hover { text-decoration: underline; }

#MainMenu, footer { visibility: hidden; height: 0; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stDecoration"] { display: none; }
.block-container { padding-top: 1.7rem; padding-bottom: 5rem; max-width: 1240px; }
[data-testid="stToolbar"] { right: 1rem; }
/* Hide Streamlit's built-in Deploy / main-menu buttons (not used by this
   app) while KEEPING the sidebar expand/collapse controls visible - they
   also live inside stToolbar and must not be hidden. */
[data-testid="stDeployButton"],
[data-testid="stMainMenu"],
[data-testid="stToolbar"] [data-testid="stPopoverButton"],
[data-testid="stToolbar"] [data-testid="stMainMenu"] { display: none !important; }
[data-testid="stToolbar"] [data-testid="stSidebarCollapseButton"],
[data-testid="stToolbar"] [data-testid="stExpandSidebarButton"] { display: inline-flex !important; }

::-webkit-scrollbar { width: 9px; height: 9px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 99px; }
::-webkit-scrollbar-thumb:hover { background: var(--accent); }

@keyframes ufFadeUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes ufPulse { 0%,100% { opacity: 1; } 50% { opacity: .45; } }
@keyframes ufFloat { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }

.stButton > button, [data-testid="stFormSubmitButton"] > button {
    background: var(--grad); color: #fff; font-weight: 650;
    border: none; border-radius: 12px; padding: .58rem 1.1rem;
    transition: all .18s ease; box-shadow: 0 4px 18px rgba(124,58,237,.30);
}
.stButton > button:hover:not(:disabled) {
    transform: translateY(-2px); box-shadow: 0 10px 30px rgba(124,58,237,.45);
    color: #fff;
}
.stButton > button:active:not(:disabled) { transform: translateY(0); }
.stButton > button[kind="secondary"] {
    background: var(--surface2); color: var(--text);
    border: 1px solid var(--border-strong); box-shadow: none;
}
.stButton > button[kind="secondary"]:hover:not(:disabled) {
    background: var(--surface3); color: var(--accent2);
    border-color: var(--accent); box-shadow: var(--shadow-soft);
}
.stButton > button[kind="tertiary"] {
    background: transparent; color: var(--muted);
    border: 1px solid var(--border); box-shadow: none;
}
.stButton > button[kind="tertiary"]:hover:not(:disabled) {
    color: var(--danger); border-color: var(--danger); box-shadow: none;
}

.qa-chip button {
    background: var(--surface) !important; color: var(--text) !important;
    border: 1px solid var(--border-strong) !important; border-radius: 14px !important;
    padding: .7rem .5rem !important; font-size: .92rem !important;
    box-shadow: var(--shadow-soft) !important; transition: all .18s ease !important;
    white-space: normal !important; height: auto !important;
}
.qa-chip button:hover:not(:disabled) {
    transform: translateY(-2px) !important;
    border-color: var(--accent2) !important;
    box-shadow: var(--glow) !important;
    background: var(--surface2) !important;
}

[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
[data-testid="stNumberInput"] input, [data-testid="stDateInput"] input {
    background: var(--surface2); border: 1px solid var(--border-strong);
    border-radius: 12px; color: var(--text);
}
[data-testid="stTextInput"] input:focus, [data-testid="stTextArea"] textarea:focus {
    border-color: var(--accent2); box-shadow: 0 0 0 3px var(--accent-soft);
}
[data-testid="stSelectbox"] [data-baseweb="select"] > div {
    background: var(--surface2); border: 1px solid var(--border-strong);
    border-radius: 12px; color: var(--text);
}
[data-testid="stSelectbox"] [data-baseweb="popover"] { background: var(--surface); border: 1px solid var(--border-strong); }
[data-testid="stSlider"] [role="slider"] { background: var(--accent2); }
[data-testid="stToggle"] [role="switch"] { background: var(--surface3); }
[data-testid="stToggle"] [role="switch"][aria-checked="true"] { background: var(--grad); }

[data-testid="stSegmentedControl"] [data-baseweb="tab-list"] {
    background: var(--surface2); border: 1px solid var(--border-strong);
    border-radius: 12px; padding: 4px; gap: 4px;
}
[data-testid="stSegmentedControl"] [data-baseweb="tab"] {
    border-radius: 9px !important; color: var(--muted) !important;
    background: transparent !important; font-weight: 600 !important;
}
[data-testid="stSegmentedControl"] [aria-selected="true"] {
    background: var(--grad) !important; color: #fff !important;
    box-shadow: 0 3px 12px rgba(124,58,237,.35);
}

[data-testid="stFileUploader"] {
    background: var(--surface); border: 1.5px dashed var(--border-strong);
    border-radius: 18px; transition: all .2s ease;
}
[data-testid="stFileUploader"]:hover, [data-testid="stFileUploader"]:focus-within {
    border-color: var(--accent2); box-shadow: var(--glow);
    background: var(--surface2);
}
[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] { padding: 1.4rem; }
[data-testid="stFileUploader"] button {
    background: var(--surface3); color: var(--text); border: 1px solid var(--border-strong); border-radius: 10px;
}
[data-testid="stFileUploader"] [data-testid="stFileUploaderFile"] { background: var(--surface2); border-radius: 10px; }

[data-testid="stTabs"] [data-baseweb="tab-list"] { gap: 6px; }
[data-testid="stTabs"] [data-baseweb="tab"] {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 11px; padding: 8px 18px; font-weight: 600;
    color: var(--muted); transition: all .15s ease;
}
[data-testid="stTabs"] [data-baseweb="tab"]:hover { color: var(--accent2); border-color: var(--border-strong); }
[data-testid="stTabs"] [aria-selected="true"] {
    background: var(--grad) !important; color: #fff !important; border-color: transparent !important;
}
[data-testid="stExpander"] {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 15px; overflow: hidden;
}
[data-testid="stExpander"] summary { font-weight: 650; }
[data-testid="stAlert"] { border-radius: 13px; border: 1px solid var(--border); background: var(--surface); }
[data-testid="stDataFrame"] { border: 1px solid var(--border); border-radius: 15px; overflow: hidden; }
[data-testid="stDataFrame"] table { background: var(--surface); color: var(--text); }
[data-testid="stProgress"] [role="progressbar"] > div > div > div > div {
    background: var(--grad);
}

/* ---------- Chat messages ---------- */
[data-testid="stChatMessage"] {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 18px;
    padding: 16px 18px;
    margin: 12px 0;
    box-shadow: var(--shadow-soft);
    animation: ufFadeUp .3s ease;
}
[data-testid="stChatMessage"]:hover { border-color: var(--border-strong); }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    background: linear-gradient(135deg, rgba(124,58,237,.20), rgba(168,85,247,.14));
    border-color: rgba(168,85,247,.30);
    margin-left: 12%;
    border-radius: 18px 18px 6px 18px;
}
[data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"] {
    background: var(--grad);
    color: #fff !important;
    font-weight: 700;
    box-shadow: 0 4px 12px rgba(124,58,237,.40);
    border: 2px solid rgba(255,255,255,.14);
}
[data-testid="stChatMessageAvatarUser"] { border-radius: 14px 14px 14px 4px; }

[data-testid="stChatInput"] {
    background: var(--surface);
    border: 1.5px solid var(--border-strong);
    border-radius: 18px;
    padding: .4rem .6rem;
    box-shadow: var(--shadow-soft);
    transition: all .18s ease;
}
[data-testid="stChatInput"]:focus-within {
    border-color: var(--accent2);
    box-shadow: var(--glow);
}
[data-testid="stChatInput"] textarea { background: transparent !important; color: var(--text) !important; font-size: 1rem !important; }
[data-testid="stChatInput"] button {
    background: var(--grad) !important; color: #fff !important;
    border-radius: 12px !important; box-shadow: 0 4px 14px rgba(124,58,237,.35) !important;
}

[data-testid="stSidebar"] [role="radiogroup"] { gap: 3px; display: flex; flex-direction: column; }
[data-testid="stSidebar"] [role="radiogroup"] label {
    display: flex; align-items: center; gap: 11px;
    padding: 10px 14px; border-radius: 12px; cursor: pointer;
    border: 1px solid transparent; transition: all .16s ease;
    position: relative;
}
[data-testid="stSidebar"] [role="radiogroup"] label p { color: var(--muted); font-weight: 550; font-size: .95rem; }
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background: var(--accent-soft); }
[data-testid="stSidebar"] [role="radiogroup"] label:hover p { color: var(--text); }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
    background: linear-gradient(135deg, rgba(124,58,237,.28), rgba(168,85,247,.16));
    border-color: rgba(168,85,247,.45);
    box-shadow: inset 3px 0 0 var(--accent2);
}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p { color: var(--text); font-weight: 700; }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) span,
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) [data-testid="stIconMaterial"] {
    color: var(--accent2) !important;
}
[data-testid="stSidebar"] [role="radiogroup"] input { display: none; }

[data-testid="stSidebarCollapsedControl"], [data-testid="stSidebarCollapseButton"] {
    color: var(--accent2) !important; background: var(--accent-soft) !important;
    border: 1px solid rgba(168,85,247,.4) !important; border-radius: 9px !important;
}
[data-testid="stSidebarCollapsedControl"]:hover, [data-testid="stSidebarCollapseButton"]:hover {
    background: var(--grad) !important; color: #fff !important;
    box-shadow: 0 4px 14px rgba(124,58,237,.4) !important;
}
[data-testid="stSidebarCollapsedControl"] svg, [data-testid="stSidebarCollapseButton"] svg { color: var(--accent2) !important; fill: var(--accent2) !important; }
[data-testid="stSidebarCollapsedControl"]:hover svg, [data-testid="stSidebarCollapseButton"]:hover svg { color: #fff !important; fill: #fff !important; }

/* ---------- Custom components ---------- */
.grad-text {
    background: var(--grad);
    -webkit-background-clip: text; background-clip: text; color: transparent;
}
.side-section {
    font-size: 10.5px; font-weight: 700; letter-spacing: .12em;
    text-transform: uppercase; color: var(--muted);
    margin: 22px 6px 8px;
}
.side-row { display: flex; align-items: center; gap: 8px; padding: 5px 0; font-size: 13px; }
.side-ico { width: 22px; text-align: center; font-size: 13px; opacity: .9; }
.side-label { color: var(--muted); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.side-val { color: var(--text); font-weight: 650; font-size: 12.5px; }

.side-brand { display: flex; align-items: center; gap: 12px; padding: 6px 4px 4px; }
.side-logo {
    width: 42px; height: 42px; border-radius: 13px; flex-shrink: 0;
    background: var(--grad); display: flex; align-items: center; justify-content: center;
    font-size: 20px; box-shadow: 0 6px 20px rgba(124,58,237,.45);
    animation: ufFloat 4s ease-in-out infinite;
}
.side-name { font-size: 15px; font-weight: 780; letter-spacing: -.01em; line-height: 1.2; }
.side-tag { font-size: 11px; color: var(--muted); }

.user-chip {
    display: flex; align-items: center; gap: 10px; margin-top: 14px;
    padding: 10px 12px; border: 1px solid var(--border);
    border-radius: 14px; background: var(--surface);
    box-shadow: var(--shadow-soft);
}
.avatar {
    width: 36px; height: 36px; border-radius: 12px; flex-shrink: 0;
    background: var(--grad); color: #fff; font-weight: 700; font-size: 14px;
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 4px 12px rgba(124,58,237,.35);
}
.user-name { font-size: 13.5px; font-weight: 700; line-height: 1.2; }
.user-role { font-size: 11px; color: var(--muted); }

.page-head { margin-bottom: 24px; animation: ufFadeUp .35s ease; }
.page-title { display: flex; align-items: center; gap: 13px; font-size: 26px; font-weight: 800; letter-spacing: -.025em; }
.page-icon {
    width: 46px; height: 46px; border-radius: 14px; flex-shrink: 0;
    background: var(--grad); display: flex; align-items: center; justify-content: center;
    font-size: 22px; box-shadow: 0 8px 24px rgba(124,58,237,.42);
}
.page-sub { color: var(--muted); margin-top: 7px; font-size: 14px; }

.fx-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 18px; padding: 20px; transition: all .2s ease;
    animation: ufFadeUp .3s ease;
}
.fx-card:hover { border-color: var(--border-strong); box-shadow: var(--shadow); }
.fx-card h4 { margin: 0 0 4px; font-size: 15px; font-weight: 720; }
.fx-card .fx-sub { color: var(--muted); font-size: 12.5px; margin-bottom: 12px; }

.fx-metric {
    background: linear-gradient(180deg, var(--surface), var(--surface2));
    border: 1px solid var(--border); border-radius: 18px;
    padding: 18px 20px; transition: all .2s ease; height: 100%;
    position: relative; overflow: hidden;
}
.fx-metric::after {
    content: ""; position: absolute; inset: auto -30% -60% auto; width: 120%; height: 80%;
    background: radial-gradient(140px 80px at 85% 100%, rgba(168,85,247,.18), transparent 70%);
    pointer-events: none;
}
.fx-metric:hover { transform: translateY(-3px); border-color: var(--border-strong); box-shadow: var(--shadow); }
.fx-metric-row { display: flex; align-items: center; gap: 10px; }
.fx-icon {
    width: 36px; height: 36px; border-radius: 11px; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center; font-size: 17px;
    background: var(--accent-soft); border: 1px solid var(--border);
}
.fx-label { color: var(--muted); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .07em; }
.fx-value { margin-top: 12px; font-size: 27px; font-weight: 780; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
.fx-value small { font-size: 13px; color: var(--muted); font-weight: 500; }
.fx-hint { color: var(--muted); font-size: 11.5px; margin-top: 4px; }

.pill {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 3px 12px; border-radius: 999px; font-size: 12px; font-weight: 650;
    white-space: nowrap;
}
.pill.ok { background: rgba(52,211,153,.14); color: var(--success); border: 1px solid rgba(52,211,153,.35); }
.pill.err { background: rgba(251,113,133,.14); color: var(--danger); border: 1px solid rgba(251,113,133,.35); }
.pill.warn { background: rgba(251,191,36,.14); color: var(--warn); border: 1px solid rgba(251,191,36,.35); }
.pill.info { background: var(--accent-soft); color: var(--accent2); border: 1px solid rgba(168,85,247,.35); }
.pill.dot::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

.meta-bar {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--border);
}
.meta-chip {
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 11.5px; font-weight: 600; color: var(--muted);
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 999px; padding: 4px 11px;
}
.meta-chip b { color: var(--text); font-weight: 650; }
.live-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent2); animation: ufPulse 1.2s infinite; }

.typing-dots { display: inline-flex; gap: 5px; align-items: center; }
.typing-dots span { width: 7px; height: 7px; border-radius: 50%; background: var(--accent2); animation: ufPulse 1.1s infinite; }
.typing-dots span:nth-child(2) { animation-delay: .18s; }
.typing-dots span:nth-child(3) { animation-delay: .36s; }

.uf-copy {
    background: var(--surface2); color: var(--muted);
    border: 1px solid var(--border-strong); border-radius: 9px;
    font-size: 12px; font-weight: 600; padding: 4px 12px; cursor: pointer;
    transition: all .15s ease; font-family: inherit;
}
.uf-copy:hover { color: var(--accent2); border-color: var(--accent2); box-shadow: var(--glow); }

.workflow-banner {
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    margin-bottom: 12px; padding: 10px 14px;
    background: linear-gradient(135deg, rgba(124,58,237,.18), rgba(168,85,247,.10));
    border: 1px solid rgba(168,85,247,.30); border-radius: 14px;
}
.wf-steps { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.wf-step {
    display: inline-flex; align-items: center; gap: 5px;
    font-size: 11.5px; font-weight: 650; padding: 4px 10px; border-radius: 999px;
    background: var(--surface2); color: var(--muted); border: 1px solid var(--border);
}
.wf-step.done { background: rgba(52,211,153,.12); color: var(--success); border-color: rgba(52,211,153,.35); }

.qa-prompt {
    margin: 14px 0 6px; padding: 13px 16px;
    background: linear-gradient(135deg, rgba(124,58,237,.18), rgba(168,85,247,.10));
    border: 1px solid rgba(168,85,247,.35); border-radius: 14px;
    font-size: 14.5px; font-weight: 600; color: var(--text);
    animation: ufFadeUp .25s ease;
}

.empty-hero { text-align: center; padding: 3.2rem 1.5rem 2rem; animation: ufFadeUp .4s ease; }
.empty-hero .eh-icon {
    width: 72px; height: 72px; margin: 0 auto 1.1rem; border-radius: 22px;
    background: var(--grad); display: flex; align-items: center; justify-content: center;
    font-size: 34px; box-shadow: 0 14px 40px rgba(124,58,237,.5);
    animation: ufFloat 3.5s ease-in-out infinite;
}
.empty-hero h2 { font-size: 1.55rem; font-weight: 800; margin: 0 0 .4rem; letter-spacing: -.02em; }
.empty-hero .eh-sub { color: var(--muted); font-size: .95rem; max-width: 520px; margin: 0 auto; }

.file-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 16px; padding: 14px; transition: all .2s ease;
    height: 100%; position: relative; overflow: hidden;
}
.file-card:hover { border-color: var(--border-strong); box-shadow: var(--shadow); transform: translateY(-2px); }
.file-card .fc-icon {
    width: 44px; height: 44px; border-radius: 13px; font-size: 20px;
    display: flex; align-items: center; justify-content: center;
    background: var(--accent-soft); border: 1px solid var(--border); margin-bottom: 10px;
}
.file-card .fc-name { font-weight: 700; font-size: 13.5px; word-break: break-all; line-height: 1.3; }
.file-card .fc-meta { color: var(--muted); font-size: 11.5px; margin-top: 4px; }

.upload-tip { color: var(--muted); font-size: 12.5px; margin-top: 8px; }
.preview-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }

.kv-row { display: flex; justify-content: space-between; padding: 7px 0; border-bottom: 1px dashed var(--border); font-size: 13px; }
.kv-row:last-child { border-bottom: none; }
.kv-row .k { color: var(--muted); }
.kv-row .v { font-weight: 650; }

.legal-body p { margin: 0 0 12px; font-size: .95rem; }
.legal-body h3 { margin: 18px 0 6px; font-size: 1.02rem; }

.auth-brand { padding: 10px 10px 10px 0; max-width: 560px; }
.auth-brand .auth-logo {
    width: 60px; height: 60px; border-radius: 18px;
    background: var(--grad); display: flex; align-items: center; justify-content: center;
    font-size: 29px; box-shadow: 0 12px 34px rgba(124,58,237,.5); margin-bottom: 24px;
    animation: ufFloat 4s ease-in-out infinite;
}
.auth-brand h1 { font-size: 2.5rem; font-weight: 820; letter-spacing: -.03em; line-height: 1.1; margin: 0 0 16px; }
.auth-brand .auth-desc { color: var(--muted); font-size: 1rem; margin-bottom: 26px; }
.auth-feat { display: flex; gap: 13px; padding: 12px 0; align-items: flex-start; }
.auth-feat .fi {
    width: 36px; height: 36px; border-radius: 11px; flex-shrink: 0;
    background: var(--accent-soft); border: 1px solid var(--border);
    display: flex; align-items: center; justify-content: center; font-size: 16px;
}
.auth-feat .ft { font-size: 14px; font-weight: 650; }
.auth-feat .fd { font-size: 12.5px; color: var(--muted); margin-top: 2px; }
.auth-stats { display: flex; gap: 26px; margin-top: 26px; }
.auth-stats .as-n { font-size: 22px; font-weight: 800; background: var(--grad); -webkit-background-clip: text; background-clip: text; color: transparent; }
.auth-stats .as-l { color: var(--muted); font-size: 11.5px; text-transform: uppercase; letter-spacing: .06em; margin-top: 2px; }

.auth-card-head { margin-bottom: 16px; }
.auth-card-head h2 { font-size: 21px; font-weight: 760; margin: 0 0 3px; }
.auth-card-head p { color: var(--muted); font-size: 13.5px; margin: 0; }
[data-testid="stForm"] {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 20px; padding: 26px 26px 10px; box-shadow: var(--shadow);
}
.auth-foot { text-align: center; color: var(--muted); font-size: 12px; margin-top: 18px; }
.auth-divider {
    display: flex; align-items: center; gap: 12px;
    color: var(--muted); font-size: 12.5px; margin: 20px 0 4px;
}
.auth-divider::before, .auth-divider::after { content: ""; flex: 1; height: 1px; background: var(--border-strong); }

[data-testid="stSidebar"] .auth-foot { text-align: left; margin-top: 14px; }
"""


def theme_css(active_theme: str = "dark", font_size: str = "md") -> str:
    """Full stylesheet for the app. font_size: sm | md | lg | xl."""
    sizes = {"sm": "14px", "md": "15.5px", "lg": "17px", "xl": "18.5px"}
    root_fs = sizes.get(font_size, "15.5px")
    vars_block = _DARK_VARS if active_theme != "light" else _LIGHT_VARS
    return (
        "<style>"
        f"html, body, .stApp {{ font-size: {root_fs}; }}"
        f"{vars_block}{_BASE_CSS}"
        "</style>"
    )


def copy_js() -> str:
    """Global script that powers the 'Copy' buttons on chat responses.

    The payload travels as a base64 token (single safe attribute value), so
    multi-line code with quotes never breaks the button's HTML.
    """
    return """
    <script>
    function ufB64ToText(b64) {
        var bin = atob(b64);
        var bytes = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) { bytes[i] = bin.charCodeAt(i); }
        return new TextDecoder('utf-8').decode(bytes);
    }
    function ufCopy(b64, btn) {
        var txt;
        try { txt = ufB64ToText(b64); } catch(e) { txt = b64; }
        function done() {
            if (btn) { btn.textContent = '\u2713 Copied';
                setTimeout(function(){ btn.textContent = 'Copy'; }, 1600); }
        }
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(txt).then(done, function(){
                try { window.prompt('Copy to clipboard:', txt); } catch(e) {}
            });
        } else {
            var ta = document.createElement('textarea');
            ta.value = txt; document.body.appendChild(ta); ta.select();
            try { document.execCommand('copy'); } catch(e) {}
            document.body.removeChild(ta); done();
        }
    }
    </script>
    """


# ----------------------------------------------------------------------
# Component builders
# ----------------------------------------------------------------------

def page_header(icon: str, title: str, subtitle: str) -> str:
    return (
        '<div class="page-head">'
        f'<div class="page-title"><span class="page-icon">{icon}</span>{_esc(title)}</div>'
        f'<div class="page-sub">{_esc(subtitle)}</div>'
        "</div>"
    )


def metric_card(label: str, value, icon: str, hint: str = "") -> str:
    hint_html = f'<div class="fx-hint">{_esc(hint)}</div>' if hint else ""
    return (
        '<div class="fx-metric">'
        '<div class="fx-metric-row">'
        f'<span class="fx-icon">{icon}</span>'
        f'<span class="fx-label">{_esc(label)}</span>'
        "</div>"
        f'<div class="fx-value">{_esc(value)}</div>'
        f"{hint_html}"
        "</div>"
    )


def pill(kind: str, text: str, dot: bool = False) -> str:
    cls = kind if kind in {"ok", "err", "warn", "info"} else "info"
    return f'<span class="pill {cls}{" dot" if dot else ""}">{_esc(text)}</span>'


def side_row(icon: str, label: str, value: str) -> str:
    return (
        f'<div class="side-row"><span class="side-ico">{icon}</span>'
        f'<span class="side-label">{_esc(label)}</span>'
        f'<span class="side-val">{_esc(value)}</span></div>'
    )


def side_section(title: str) -> str:
    return f'<div class="side-section">{_esc(title)}</div>'


def brand_html(name: str = "AI Coding Assistant", tagline: str = "Your AI engineering team") -> str:
    return (
        '<div class="side-brand">'
        '<div class="side-logo">&#9889;</div>'
        f'<div><div class="side-name">{_esc(name)}</div><div class="side-tag">{_esc(tagline)}</div></div>'
        "</div>"
    )


def user_chip(username: str, role: str) -> str:
    username = _esc(username)
    role = _esc(role)
    initial = (username or "?").strip()[0].upper()
    return (
        '<div class="user-chip">'
        f'<div class="avatar">{initial}</div>'
        f'<div><div class="user-name">{username}</div><div class="user-role">{role}</div></div>'
        f'{pill("info", role)}'
        "</div>"
    )


def empty_state(icon: str, title: str, subtitle: str) -> str:
    return (
        '<div class="empty-hero">'
        f'<div class="eh-icon">{icon}</div>'
        f"<h2>{_esc(title)}</h2>"
        f'<div class="eh-sub">{_esc(subtitle)}</div>'
        "</div>"
    )


def meta_bar(chips) -> str:
    """chips: list of (icon, label, bold) tuples rendered as meta chips."""
    parts = []
    for icon, label, is_bold in chips:
        if is_bold:
            parts.append(f'<span class="meta-chip">{icon} <b>{label}</b></span>')
        else:
            parts.append(f'<span class="meta-chip">{icon} {label}</span>')
    return f'<div class="meta-bar">{"".join(parts)}</div>'


def workflow_banner(stages: list, done: int) -> str:
    step_html = []
    for i, name in enumerate(stages):
        cls = "wf-step done" if i < done else "wf-step"
        check = "&#10003;" if i < done else f"{i + 1}"
        step_html.append(f'<span class="{cls}">{check} {_esc(name)}</span>')
    return (
        '<div class="workflow-banner">'
        f'{pill("ok", "&#10003; Workflow completed", dot=True)}'
        f'<div class="wf-steps">{"".join(step_html)}</div>'
        "</div>"
    )


def copy_button(text: str) -> str:
    """Copy button that carries its payload as base64 (quote/newline safe)."""
    import base64
    token = base64.b64encode(str(text).encode("utf-8")).decode("ascii")
    return (
        "<button class=\"uf-copy\" onclick=\"ufCopy(this.getAttribute('data-b64'), this)\" "
        f"data-b64=\"{token}\">Copy</button>"
    )
