# 🤖 Multi-AI-Agent Coding Assistant

> **One workspace to chat, code, debug, document, plan and analyze** — every request is routed automatically to the right specialized AI agent by an intelligent Decision Engine.

![System Architecture](assets/architecture.png)

---

## 📌 Overview

The **Multi-AI-Agent Coding Assistant** is a full-stack AI software-engineering platform built with **Python + Streamlit**. Instead of a single chat model doing everything, the system separates **decision making, workflow orchestration, task execution, tool interaction, security validation and memory** into independent, swappable components.

The platform includes:

- 🧠 **Intelligent Decision Engine** — classifies every request (LLM-first, keyword fallback)
- 🤝 **Coordinator Agent** — routes requests and orchestrates the pipeline
- 🤖 **8 Specialized AI Agents** — chat, coding, debugging, docs, planning, project analysis, review, code analysis
- 🔄 **Collaborative Workflow** — Planner → Coding → Reviewer → Code Analysis → Documentation
- 🛠 **Enterprise Tool Framework** — file ops, code execution, patching, GitHub, code metrics
- 🔌 **MCP Layer** — 7 model-context-protocol servers (GitHub, filesystem, search, database, Python exec, knowledge, git)
- 🔐 **Security & Validation** — LLM guard, action validator, security guard, code cleaner
- 💾 **Hybrid Memory** — short-term context/facts, long-term history, shared memory, RAG knowledge index
- 🗄️ **Persistence & API** — SQLite database + dependency-free REST API
- 👤 **Auth & RBAC** — Google / Email / Guest login with admin / developer / guest roles

---

## ✨ Features

### 🤖 Multi-Agent Intelligence
| Agent | Responsibility |
|---|---|
| **Chat Assistant** | General conversation, Q&A, concept explanations |
| **Coding Agent** | Generates code, creates files, implements features |
| **Debugging Agent** | Root-causes errors, explains bugs, suggests fixes |
| **Documentation Agent** | Writes docs, explains code, describes projects |
| **Planner Agent** | Breaks tasks into plans, designs architectures |
| **Project Analyzer** | Analyzes project structure, gives insights |
| **Reviewer Agent** | Critiques code for bugs and quality issues |
| **Code Analysis Agent** | Analyzes/reviews/quality-checks existing code |

### 🔄 Collaborative Workflow
Clicking **"Build an app"** runs the full 5-stage pipeline — each agent reads the previous stage's output from Shared Memory:

```
Planner Agent → Coding Agent → Reviewer Agent → Code Analysis Agent → Documentation Agent
```

Results render in 5 tabs: 📋 Plan / 💻 Code / 🔍 Review / 🧪 Analysis / 📄 Docs.

### 🧠 Memory & Routing Intelligence
- **Memory Store / Recall** — tell the assistant *"My name is Muskan"* and it remembers; ask *"What is my name?"* and it recalls. The UI shows a **routing-analysis pill** explaining how each request was classified.
- Requests route correctly even for tricky phrasing like *"Who is my favourite person?"* (recall, not store).

### 🔑 GitHub Token via Chat
Type `set my github token ghp_xxx` in the chat — the token is saved to `.env`, the process env, and the live MCP server instantly (no restart, no LLM call). GitHub stays hidden in the UI until you actually use a repository feature.

### 🎨 Consumer-Grade UI (theme.py + user_files.py)
- Split-panel **auth screen** with Google / Email / Guest login
- **Dark purple design system** — rounded cards, soft shadows, smooth animations (dark-only, English-only)
- Sidebar with violet active states: **🏠 Workspace · 📂 My Files · 📊 Analytics · 📜 Chat History · ⚙️ Settings · 👤 User Profile · 🚪 Logout**
- **Workspace** — 9 quick actions (Build Application, Chat Assistant, Write Code, Debug, Explain, Review, Code Analysis, Analyze Project, Documentation) that **ask what you need first** instead of firing canned prompts; drag & drop uploads; rich chat with agent/model/time meta, Copy, Download, Regenerate and Stop
- **My Files** — private per-user upload library (never internal project folders): preview, download, rename, delete, search, filter
- **Analytics** — 5 KPI cards + 4 usage charts, every number derived from real database records
- **Chat History** — search across conversations and messages, open or export any chat
- **Legal pages** — Terms, Privacy, Help Center, What's new
- API keys and GitHub tokens are **never shown in the UI** — they stay internal

---

## 🏗️ System Architecture

```
                         User
                           │
                           ▼
                Streamlit Chat Interface (app.py + theme.py)
                           │
                           ▼
              Auth: Google / Email / Guest · RBAC · Sessions
                           │
                           ▼
                  Intelligent Decision Engine
              (Intent Detection & Task Routing)
                           │
                           ▼
                    Coordinator Agent
              (Workflow Orchestration Layer)
                           │
          ┌────────────────┼────────────────┐
          │                                │
          ▼                                ▼
 Specialized AI Agents            Enterprise Tool Framework
 (8 agents)                       (File, Executor, Patch, GitHub, …)
 + Workflow Manager               + MCP Layer (7 servers)
          │                                │
          └────────────────┬───────────────┘
                           ▼
              Security & Validation
            (LLM Guard · Action Validator · Security Guard)
                           │
                           ▼
                    Prompt System
                           │
                           ▼
              Multi-Provider LLM (Groq/OpenAI/Gemini/Anthropic/Ollama)
                           │
                           ▼
                    Hybrid Memory Layer
         (Short-Term · Long-Term · Shared · Tool History · RAG)
                           │
                           ▼
          Persistence & API (SQLite · REST API · Logger · Analytics)
```

---

## 🧩 Component Breakdown

### 🧠 Decision Engine (`agents/decision_engine.py`)
- **LLM-first classification** with a category prompt, **keyword fallback** when the LLM is unavailable.
- Handles 14 categories: `github, project, debug, documentation, planner, execution, patch, file, coding, memory_store, memory_recall, workflow, chat, code_analysis`.
- Memory fast-path: unambiguous personal statements and recall questions are detected before any LLM call.

### 🤝 Coordinator Agent (`agents/coordinator.py`)
- Receives the decision, routes to the right agent/tool, stores turns in short-term memory.
- Handlers: memory store/recall, chat, workflow, GitHub (via MCP), project analysis, code analysis, debugging, documentation, planner, patch, file, coding (+ optional execution).
- Every route logs to the execution tracker and the database.

### 🔌 MCP Layer (`mcp/`)
| Server | Capabilities |
|---|---|
| **GitHub** | repo info, branches, commits, tree, file browse, stats, issues, PRs, releases, contributors, rate limit |
| **Filesystem** | safe file read/write (path-escape protected) |
| **Search** | content search |
| **Database** | read-only queries (writes blocked) |
| **Python Exec** | sandboxed execution with error capture |
| **Knowledge** | RAG-backed knowledge retrieval |
| **Git** | local git operations |

All GitHub operations flow through `MCPManager.call("github", action, params)`.

### 🛠 Tools (`tools/`)
File Tool · Code Executor · Patch Tool · Project Analyzer · GitHub Tool · Multi-File Parser · Patch Parser · Action Validator · Execution Tracker · Code Metrics · Report Exporter · Security Guard · LLM Guard · Code Cleaner · Logger · Tool Manager

### 💾 Memory (`memory/`)
`ShortTermMemory` (context + facts) · `Memory` (long-term `history.json`) · `SharedMemory` (workflow stage handoff) · `ExecutionTracker` (`tool_execution_history.json`)

### 🗄️ Database (`database/db.py`)
SQLite (zero-config, PostgreSQL-ready) tables: users, sessions, conversations, messages, memory_facts, workflows, executions, **tool_logs** (powers the Analytics Tool Usage chart), agent_logs, analytics, github_activity, projects, settings.

### 🌐 REST API (`api/server.py`)
Dependency-free JSON API on stdlib `http.server`:
```
POST /api/login, /api/chat, /api/code, /api/debug, /api/analyze,
     /api/project, /api/github, /api/workflow
GET  /api/dashboard, /api/health
```

### 🧪 Testing
- **93 automated tests** (`pytest tests/`): coordinator routing, decision engine, MCP, enterprise MCP, knowledge MCP, RAG, database, API, tools, code metrics, report exporter, settings, short-term memory, Google OAuth.
- **12 real-LLM agent smoke tests** (`scripts/test_each_agent.py`).

---

## 🚀 Getting Started

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) Configure API keys in .env
#    GROQ_API_KEY=...            (default provider)
#    GITHUB_TOKEN=...            (optional, for GitHub tool)

# 3. Launch the UI
streamlit run app.py
# → http://localhost:8501   (default admin: admin / admin123, auto-created)

# 4. Run the CLI version
python main.py

# 5. Run tests
pytest tests/ -q
python scripts/test_each_agent.py
```

**Quick start in the UI:**
- Type `My name is Muskan` → stored; `What is my name?` → recalled
- Pick a **quick action** (e.g. ⚙️ Build Application) → it asks what you need, then runs
- Type `set my github token ghp_xxx` → GitHub tool becomes authenticated
- Click **⚙️ Build Application** → full 5-agent workflow, then **"Done — back to chat"**
- Upload a `.py` file, then type `analyse it` / `review it` / `generate documentation` → routed to the correct agent
- Ask `Show repo info for tensorflow/tensorflow` → GitHub via MCP

---

## 📁 Project Structure

```
├── agents/            # Decision engine, coordinator, 8 specialized agents
├── api/               # Dependency-free REST API server
├── assets/            # architecture.png (regenerate via scripts/generate_architecture.py)
├── auth/              # AuthService: hashing, sessions, RBAC, Google/Email/Guest
├── config/            # Settings service (DB-backed), provider models, env keys
├── database/          # SQLite layer (enterprise.db)
├── logsys/            # Enterprise logger
├── mcp/               # MCP manager + 7 servers (base.py, manager.py, servers/)
├── memory/            # Short-term, long-term, shared, storage, tool history
├── models/            # LLM wrapper + model manager (multi-provider)
├── prompts/           # Agent prompt templates
├── rag/               # Knowledge indexer (RAG)
├── scripts/           # generate_architecture.py, test_each_agent.py, fix_template_gaps.py, polish_agile_template.py
├── templates/         # Agile / Defect Tracker / Unit Test Plan workbooks
├── tests/             # 93 automated tests
├── tools/             # Enterprise tool framework + security guards
├── user_files.py      # Private per-user upload library (user_data/uploads/)
├── workflow/          # WorkflowManager (5-stage collaborative pipeline)
├── app.py             # Streamlit UI (Workspace, My Files, Analytics, History, Settings, Profile)
├── theme.py           # Design system: CSS themes + HTML builders
└── main.py            # CLI entry point
```

---

## 🛠 Technologies

Python · Streamlit · SQLite · Groq / OpenAI / Gemini / Anthropic / Ollama (LLM) · Requests · MCP (Model Context Protocol) · Pillow (diagrams) · pytest · stdlib http.server (API) · PBKDF2-SHA256 (auth)

---

## 📋 Project Templates

The `templates/` folder ships filled agile workbooks tracking the whole project:

- **Agile_Template_Filled.xlsx** — Product Backlog, Sprint Backlog (with day grids), Stand-up Meeting, Retrospection — Sprints 1–3
- **Defect_Tracker_Filled.xlsx** — every bug found and fixed, by sprint
- **Unit_Test_Plan_Filled.xlsx** — test cases TC-001…TC-032

Sprint 3 rows reflect the current state of the product (consumer UI, quick actions, My Files, exact analytics, upload dedupe and attached-file routing). Sprint 1 & 2 document the original milestones. Rows are kept contiguous with `scripts/fix_template_gaps.py`, and Sprint Backlog / Retrospection polish is handled by `scripts/polish_agile_template.py` (both idempotent).

---

## ✅ Conclusion

The **Multi-AI-Agent Coding Assistant** (v2.1.0) demonstrates a production-style multi-agent architecture: an intelligent Decision Engine routes requests to specialized agents, a Coordinator orchestrates them, a collaborative Workflow chains five agents together, enterprise tools + MCP servers enable real operations, a hybrid memory + database layer persists everything, and a consumer-grade Streamlit UI makes it all feel like a modern commercial AI product — validated by 93 automated tests.
