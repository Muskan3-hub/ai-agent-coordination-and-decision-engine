import ast
import os
import re

from models.llm import LLM

from config.settings import Settings

from agents.decision_engine import DecisionEngine
from agents.coding_agent import CodingAgent
from agents.debugging_agent import DebuggingAgent
from agents.documentation_agent import DocumentationAgent
from agents.planner import Planner
from agents.chat_agent import ChatAgent
from agents.project_analyzer_agent import ProjectAnalyzer
from agents.reviewer_agent import ReviewerAgent
from agents.code_analysis_agent import CodeAnalysisAgent
from agents.response_directives import directives_block, extract_directives


from workflow.workflow_manager import WorkflowManager

from memory.context_builder import ContextBuilder
from memory.entity_memory import EntityMemory
from memory.summary_memory import SummaryMemory

from mcp import MCPManager

from tools.code_cleaner import clean_code, has_patch_instructions, strip_action_instructions
from tools.file_tool import FileTool
from tools.multi_file_parser import MultiFileParser
from tools.patch_parser import PatchParser
from tools.patch_tool import PatchTool
from tools.action_validator import ActionValidator
from tools.github_tool import GitHubTool
from tools.execution_tracker import ExecutionTracker
from tools.logger import logger

PROTECTED_FILES = {
    "app.py",
    "main.py",
    "agents/coordinator.py",
}


def count_words(text):
    """Count the words of a prose answer for word-count constraints.

    List markers (-, *, bullet, "1.", "2)") at the start of a line are
    formatting, not words: a bullet-point answer of N points therefore
    counts the same as the equivalent prose answer, so an exact-word
    request like "exactly 80 words, using only bullet points" is judged
    fairly instead of counting every "-" as a word.
    """
    n = 0
    for line in (text or "").splitlines():
        line = re.sub(r"^\s*(?:[-*\u2022]|\d{1,3}[.)])\s+", "", line)
        n += len(re.findall(r"\S+", line))
    return n


# ----------------------------------------------------------------------
# Per-task model selection.
#
# Every agent shares the app's default model by default; setting a model
# here gives a task its own model instance (same provider/API key, only
# the model name differs). The idea: cheaper/faster models handle the
# high-volume tasks, while a stronger model is reserved for the deep-
# thinking tasks. The previous Llama 3.x IDs were decommissioned on
# Groq (Aug 16), so the split now uses GPT-OSS: 20B for the high-volume
# tasks, 120B for planner/reviewer/analysis. Leave a task out of the
# map (or unset it) to fall back to the default model.
# ----------------------------------------------------------------------
CHEAP_MODEL = "openai/gpt-oss-20b"
STRONG_MODEL = "openai/gpt-oss-120b"

TASK_MODELS = {
    "chat": CHEAP_MODEL,            # casual Q&A - 8b is fine
    "coding": CHEAP_MODEL,          # simple code - 8b is fine
    "debugging": CHEAP_MODEL,       # quick root-cause - 8b is fine
    "documentation": CHEAP_MODEL,   # docs - 8b is fine
    "planner": STRONG_MODEL,        # architecture/plans - keep the smart one
    "reviewer": STRONG_MODEL,       # code review - keep the smart one
    "code_analysis": STRONG_MODEL,  # deep analysis - keep the smart one
    "project_analysis": STRONG_MODEL,
    "decision": CHEAP_MODEL,        # request routing - 8b is fine
}


def _model_for(task, default_model):
    """Return a dedicated LLM instance for a task, or the default model.

    Per-task models only apply when the default model is the built-in
    LLM facade and the active provider is Groq (the model IDs above are
    Groq names). Tests and callers that pass their own model keep it for
    every agent.
    """
    name = TASK_MODELS.get(task)
    if not name or not isinstance(default_model, LLM):
        return default_model
    try:
        from config.settings import Settings
        s = Settings()
        provider = s.provider
        # An explicit Model Selector choice wins over the per-task split:
        # every agent then shares the selected model (the default instance
        # also re-syncs on every call, so a mid-session switch applies to
        # the very next request without rebuilding the coordinator).
        if s.model_manual:
            return default_model
    except Exception:
        provider = "groq"
    if provider != "groq":
        return default_model
    return LLM(model=name)


class CoordinatorAgent:
    """
    Routes user requests to the correct agent / tool / workflow
    based on the Decision Engine's intent classification.
    """

    def __init__(self, model, guard, memory, short_memory):
        # ------------------------- LLM Agents -------------------------
        # Each agent gets its own model instance per TASK_MODELS above;
        # tasks without an entry share the default model.
        self.coding = CodingAgent(_model_for("coding", model), guard)
        self.debugging = DebuggingAgent(_model_for("debugging", model), guard)
        self.docs = DocumentationAgent(_model_for("documentation", model), guard)
        self.chat = ChatAgent(_model_for("chat", model), guard)
        self.planner = Planner(_model_for("planner", model), guard)
        self.project_analyzer = ProjectAnalyzer(
            _model_for("project_analysis", model), guard
        )
        self.reviewer = ReviewerAgent(_model_for("reviewer", model), guard)
        self.code_analysis = CodeAnalysisAgent(_model_for("code_analysis", model), guard)

        self.workflow_manager = WorkflowManager(
            self.planner,
            self.coding,
            self.docs
        )
        self.decision_engine = DecisionEngine(
            model=_model_for("decision", model), guard=guard
        )

        # ------------------------- Memory (upgraded) -------------------------
        self.summary_memory = SummaryMemory()
        self.entity_memory = EntityMemory()
        self.context_builder = ContextBuilder(
            short_memory=short_memory,
            summary_memory=self.summary_memory,
            entity_memory=self.entity_memory,
        )

        # ------------------------- LangGraph orchestration -------------------------
        self.graph = None
        self._workflow_graph = None
        # Compiled chain sub-graphs (Milestone 4): "review_project",
        # "debug_document", "explain_document". Cached so repeated chain
        # requests reuse the compiled graphs.
        self._chain_graphs = {}
        self._retriever = None

        # ------------------------- Core Components -------------------------
        self.model = model
        self.guard = guard
        self.memory = memory
        self.short_memory = short_memory

        # ------------------------- MCP + Tools (Non-LLM) -------------------------
        # All GitHub operations flow through the MCP layer (Task 4/5).
        self.mcp_manager = MCPManager()
        self.github_tool = GitHubTool(mcp=self.mcp_manager)

        # ------------------------- Active conversation context -----------------
        # (Milestone 5 - intelligent follow-up) Tracks what the current
        # conversation is about so terse follow-ups ("review it", "explain
        # in 100 words", "find bugs") resolve against the right subject
        # instead of being reclassified from scratch. Memory priority
        # (uploaded file > active workflow > previous response >
        # conversation > shared/short/long-term > RAG) is realized by
        # injecting this block at the top of every follow-up prompt.
        self._active = {
            "topic": None,      # compact subject of the current conversation
            "code": None,       # code generated in the current conversation
            "workflow": None,   # last Build Application workflow label
            "project_files": [],  # files of the last generated application
            "project_root": None,  # extracted root of an uploaded ZIP project
            "files": [],        # names of uploaded files still in context
            "last_response": None,
        }

    # =====================================================================
    # Helpers
    # =====================================================================
    @staticmethod
    def clean_code_output(text):
        """Backward-compatible wrapper around the centralized cleaner."""
        return clean_code(text)

    @staticmethod
    def _extract_filename(task, extensions=None):
        extensions = extensions or [".py", ".md", ".txt", ".json", ".csv"]
        for word in task.replace(",", " ").split():
            if any(word.lower().endswith(ext) for ext in extensions):
                return word
        return None

    # =====================================================================
    # Active conversation context (Milestone 5 - intelligent follow-up)
    # =====================================================================

    # Explain-style verbs: when they follow code that is already in the
    # active context, they describe THAT code, so the Documentation Agent
    # handles them instead of generic chat.
    EXPLAIN_REQUEST_RE = re.compile(
        r"\b(explain|describe|document|summarize|elaborate|clarify|comment)\b",
        re.IGNORECASE,
    )

    # Marker the UI appends for an uploaded ZIP project: the archive is
    # extracted to a per-user folder so the agents can analyze the real
    # files ("Analyze the project", "Explain structure", "Review it").
    PROJECT_MARKER_RE = re.compile(
        r"\[Attached project: [^\]]*\]\s*\(extracted to: ([^)]*)\)",
        re.IGNORECASE,
    )

    @classmethod
    def _project_root(cls, task):
        """Return the on-disk root of an uploaded (extracted) project, or
        None when the current message carries no extractable project."""
        m = cls.PROJECT_MARKER_RE.search(task or "")
        if not m:
            return None
        root = m.group(1).strip()
        return root if root and os.path.isdir(root) else None

    def _missing_project_context(self, task):
        """True when a project-level request has NO project/source context
        (no uploaded ZIP in the message or active context, no generated
        code/files/workflow).

        Answering such a request would either scan the assistant's own
        workspace or produce a generic answer, so the coordinator returns
        the friendly upload prompt instead.
        """
        if self._has_current_attachment(task):
            return False
        if not self.PROJECT_REQUEST_RE.search(self._strip_app_context(task)):
            return False
        if self._project_root(task) or self._active.get("project_root"):
            return False
        if (
            self._active.get("code")
            or self._active.get("workflow")
            or self._active.get("files")
        ):
            return False
        return True

    # Friendly prompt when a project-level request arrives with no
    # uploaded project / generated-code context - the coordinator must
    # NEVER silently analyze the assistant's own workspace.
    NO_PROJECT_MESSAGE = (
        "Please upload the project ZIP or provide the project files "
        "so I can analyze the project."
    )

    # Project-level intent: a review/analyze/plan/document/debug/fix verb
    # referring to "this/that/the/our/my project (codebase/app)". Build
    # requests ("Build a project management app") deliberately do NOT
    # match - "build" is not in the verb list.
    PROJECT_REQUEST_RE = re.compile(
        r"\b(review|analy[sz]e|plan|document(?:ation|s)?|docs?|find\s+bugs?|fix|debug)\b"
        r"[^.]*\b(this|that|the|our|my)\s+"
        r"(project|codebase|application|app)\b",
        re.IGNORECASE,
    )

    # Explicit static-metrics requests: the deterministic metrics block
    # (quality score, cyclomatic complexity, unused imports, ...) is
    # HIDDEN from normal code-analysis responses and only generated when
    # the user asks for it ("Show static metrics", "What is the
    # complexity?"...). Everything else gets the clean LLM analysis only.
    METRICS_REQUEST_RE = re.compile(
        r"\b(static metrics?|code metrics?|quality score|maintainability|"
        r"cyclomatic|complexity score|lines of code|loc\b|static analysis|"
        r"security score|documentation coverage|unused imports|unused variables|"
        r"dead code|high[- ]complexity|number of (functions|classes|imports)|"
        r"overall (quality|health) score)\b",
        re.IGNORECASE,
    )

    def _project_structure_block(self, root):
        """Concise static structure of an extracted project (folder tree,
        entry points, libraries) so agents can answer about the ACTUAL
        project without guessing. Returns None when analysis fails."""
        try:
            from tools.project_analyzer import ProjectAnalyzer as AnalyzerTool
            report = AnalyzerTool().analyze_project(root)
        except Exception:
            return None
        if not report or not report.get("structure"):
            return None
        lines = [f"Uploaded project root: {root}", "Folder structure:"]
        lines.extend(f"- {p}" for p in report["structure"][:60])
        for key, label in (
            ("entry_points", "Entry points"),
            ("libraries", "Libraries"),
        ):
            vals = report.get(key) or []
            if vals:
                lines.append(
                    f"{label}: " + ", ".join(str(v) for v in vals[:10])
                )
        return "\n".join(lines)

    def _active_has_code_context(self):
        a = self._active
        return bool(
            a.get("code") or a.get("files") or a.get("workflow")
        )

    def _active_has_real_code(self):
        """True only when the active context actually contains CODE (not
        just a conversational topic). Used to decide whether an explain-
        style follow-up describes that code ("Explain it", "Explain the
        above code") or is a general-chat question ("Explain it with an
        example" after a chat about AI) - the latter must stay in Chat,
        not be forced into the Documentation Agent."""
        a = self._active
        return bool(a.get("code") or a.get("files"))
    # Markers the UI appends after the real user request. Everything from
    # the first marker on is context, never the request itself.
    _APP_CONTEXT_MARKERS = (
        "[Attached file: ", "[Uploaded file: ",
        "[Previously generated code]",
        "[Previous assistant response]", "[Active task mode:",
    )

    # References that point back at the active topic/workflow/code.
    FOLLOWUP_REFERENCE_RE = re.compile(
        r"\b(it|its|this|above|previous|prior|the code|the app|the application|"
        r"the program|the function|the class|the file|the project|"
        r"the solution|the response|the generated|generated code|uploaded file|"
        r"the attached|the above|the output|the result|"
        r"the bug|the error|the issue|the problem|the crash)\b",
        re.IGNORECASE,
    )

    # Terse follow-up verbs: no new subject, just a verb referring back.
    TERSE_FOLLOWUP_VERBS = {
        "optimize", "refactor", "improve", "rewrite", "enhance", "simplify",
        "shorten", "review", "analyze", "analyse", "debug", "fix", "add",
        "document", "explain", "summarize", "convert", "comment", "readme",
        "elaborate", "continue", "repeat", "generate", "deploy", "update",
        "extend", "modify", "clean", "polish", "test", "run", "find",
        "handle", "validate", "guard", "catch", "sanitize", "support",
        "break", "split", "expand",
    }

    # Verbs that MODIFY existing work: with an active context they almost
    # always continue it ("Add Login Module", "Optimize it", "Convert to Java").
    MODIFY_FOLLOWUP_VERBS = {
        "optimize", "refactor", "improve", "rewrite", "enhance", "simplify",
        "shorten", "add", "extend", "modify", "clean", "polish", "convert",
        "update", "fix", "debug", "comment", "deploy", "test", "run",
        "handle", "validate", "guard", "catch", "sanitize", "support",
    }

    # Words that never count as a new subject (grammar / reference words).
    _NON_SUBJECT_WORDS = {
        "it", "its", "this", "that", "these", "those", "them", "the", "a",
        "an", "in", "with", "and", "or", "to", "for", "of", "at", "on",
        "by", "into", "from", "about", "above", "my", "our", "your", "me",
        "words", "word", "lines", "line", "language", "terms", "term",
        "detail", "details", "depth", "brief", "short", "simple", "simple",
        "easy", "basic", "example", "examples", "advantages", "disadvantages",
        "pros", "cons", "code", "app", "application", "program", "function",
        "file", "project", "architecture", "readme", "comments",
        "documentation", "it", "one", "only", "just", "exactly", "give",
        "show", "tell", "explain", "describe", "review", "analyze", "analyse",
    }

    # Relative modifiers that continue the current topic without naming it.
    RELATIVE_MODIFIERS = (
        "one example", "an example", "another example", "more examples",
        "advantages", "disadvantages", "pros and cons", "pros", "cons",
        "in simple words", "in easy language", "in simple terms",
        "in detail", "in depth", "in brief", "in short", "summarize",
        "elaborate", "in 100 words", "in 50 words", "in 200 words",
        "in 500 words", "in 10 lines", "in 5 lines",
        "find bugs", "find errors", "find issues", "any bugs", "any errors",
        # "Make the corrected code simpler" continues the previous work:
        # "corrected code" and "simpler" refer back to it.
        "corrected code", "simpler", "simplified",
        # Documentation work on the ACTIVE application/upload: the subject
        # is the previous work, not a new topic.
        "generate documentation", "api documentation", "rest api documentation",
        "generate readme", "generate docs", "generate api documentation",
    )

    @classmethod
    def _strip_app_context(cls, task):
        """Return only the real user request, cutting everything from the
        first UI-appended context marker onward."""
        pos = len(task or "")
        for marker in cls._APP_CONTEXT_MARKERS:
            i = (task or "").find(marker)
            if i != -1:
                pos = min(pos, i)
        return (task or "")[:pos].strip()

    def _classify_followup(self, task):
        """Decide whether a message continues the active conversation.

        Returns:
            "followup"  - refers back to the active topic/code/file/workflow
            "new_topic" - introduces a fresh, self-contained subject
        """
        # A message that carries an uploaded file is always about
        # that attachment - treat it as attachment-context work even on
        # the very first turn (before active context is populated).
        if self._has_current_attachment(task):
            return "followup"
        plain = self._strip_app_context(task).lower()
        if not plain:
            return "new_topic"
        active = self._active
        has_active = bool(
            active.get("topic") or active.get("code") or active.get("workflow")
            or active.get("files")
        )
        if not has_active:
            return "new_topic"

        # "if it" / "that it" are common in fresh coding requests and are
        # not references back to the assistant's previous output.
        guarded = re.sub(r"\b(if|when|that|where|whether|while)\s+it\b", " ", plain)
        has_ref = bool(self.FOLLOWUP_REFERENCE_RE.search(guarded))
        if has_ref:
            return "followup"
        if any(mod in plain for mod in self.RELATIVE_MODIFIERS):
            return "followup"

        # Verb-led phrases: modification verbs continue the active work
        # ("Add Login Module", "Optimize it"); explanation/creation verbs
        # continue it only when they carry NO new subject ("Explain it in
        # simple words" vs "Explain Operating System").
        if any(w in plain for w in self.TERSE_FOLLOWUP_VERBS):
            if any(w in plain for w in self.MODIFY_FOLLOWUP_VERBS):
                return "followup"
            subject = self._subject_words(plain)
            if not subject:
                # Pure reference: "Explain it in simple words" - the verb
                # points back, there is no subject to change the topic.
                return "followup"
            if not self._subject_refers_to_active(task, subject):
                # A single-word subject can still name a NEW topic
                # ("Explain Kubernetes" after a chat about Cloud
                # Computing): only continue when the word is generic work
                # vocabulary, matches the active topic, or the message
                # itself carries a fresh attachment.
                return "new_topic"
            return "followup"

        return "new_topic"

    # Prose-work signals: a follow-up that names prose deliverables
    # ("explanation", "summary", "readme", "audience", "words"...) is
    # conversational/documentation work even when code sits in the
    # active context - "Improve the explanation" does not mean "patch
    # the code".
    _PROSE_WORK_RE = re.compile(
        r"\b(explanation|description|summary|readme|docs|documentation|"
        r"document|comment|paragraph|text|words|audience|beginner|"
        r"programmer|developer|concept|topic|terminology|language)\b"
    )

    def _code_work_followup(self, low):
        """True when a follow-up actually acts on CODE.

        Prose-work messages ("Rewrite it for an experienced programmer")
        are never code work. Otherwise, real code in the active context
        (generated/uploaded) or code-work words in the message itself
        (python, java, function, file, api ...) make it code work.
        """
        if self._PROSE_WORK_RE.search(low):
            return False
        return (
            self._active_has_real_code()
            or bool(
                re.search(
                    r"\b(code|python|java|javascript|typescript|golang|rust|ruby|"
                    r"c\+\+|function|class|method|file|script|program|module|"
                    r"api|endpoint|app|application|stack|algorithm|binary search|"
                    r"sort|list|array|loop|variable|syntax)\b",
                    low,
                )
            )
        )

    # Terse follow-up verbs that ALWAYS act on the existing work: they
    # must route to the agent that acts on that work, no matter what the
    # LLM classifier guessed. Only applied to follow-ups (messages that
    # reference the active conversation) - fresh requests are unaffected.
    _FOLLOWUP_VERB_OVERRIDES = (
        # (regex on the stripped request, target decision)
        # Question-form advice about existing work ("What is the most
        # important improvement you would make to this file?") is CODE
        # ANALYSIS, not an imperative modify request ("Make it simpler"
        # stays Coding via the rule below).
        (r"\bwhat\b[^.]*\b(improvement|improvements|suggestion|suggestions|changes)\b", "code_analysis"),
        (r"\b(optimize|optimise|refactor|improve|rewrite|enhance|simplify|simpler|simplified|shorten|convert|add|extend|modify|update)\b", "coding"),
        (r"\breview\b", "review"),
        (r"\b(analy[sz]e|complexity)\b", "code_analysis"),
        # "bug" (singular) included so "Find a bug" / "Explain the bug"
        # follow-ups reach the Debugging Agent, not Documentation.
        # "invalid" catches error-handling follow-ups ("Also handle
        # invalid non-numeric input.") that continue a debugging session
        # but never name the word "debug"/"bug"/"error".
        (r"\b(debug|bugs|bug|fix|error|exception|crash|invalid)\b", "debug"),
        # Plan-expansion follow-ups ("Break step 3 into smaller
        # implementation tasks", "Split the roadmap into phases") stay
        # with the Planner instead of being read as code work.
        (r"\b(break|split|expand|detail)\b.*\b(step|steps|task|tasks|phase|phases|plan|planning|roadmap)\b", "planner"),
    )

    def _override_followup_decision(self, task, followup, decision, raw_task=None):
        """Correct the classified decision for terse follow-ups.

        ``task`` is the app-context-stripped request (``raw_task`` keeps
        the full message, markers included, so project attachments can
        still be detected). When the message is a follow-up on the
        active conversation, an action verb pins the routing to the
        agent that acts on the existing work ("Optimize it" -> Coding,
        "Review it" -> Reviewer, "Find bugs" -> Debugging).
        Explain/document-style verbs are handled separately so a
        conversational follow-up ("Explain it with an example" after a
        chat about AI) stays in Chat unless real code is in context.
        Messages that name a NEW subject ("Explain Operating System")
        and fresh (non-follow-up) requests are untouched.
        """
        if followup != "followup":
            return decision
        # Deterministic matching uses only the user's OWN words: cut the
        # message at the first pasted code fence or attachment marker so
        # verb patterns cannot fire on pasted code ("def add(...)") or
        # the attached project's file list ("README.md"). Without this,
        # "Analyze this Python code: ```python def add(...)``` [Attached
        # project ... README.md]" gets misread as documentation work
        # ("add" + "readme") instead of Code Analysis.
        low = re.split(
            r"(?:```|\[Attached |\[Uploaded )",
            (task or ""),
            maxsplit=1,
        )[0].lower()

        # Project-subject guard: a request that names an uploaded/active
        # PROJECT as its subject ("Analyze this project", "Inspect this
        # codebase") must reach the Project Analyzer, never Code
        # Analysis - the generic "analy[sz]e" pin below would otherwise
        # misroute it to Code Analysis, which is for CODE SNIPPETS, not
        # projects. Code-snippet requests ("Analyze this Python code",
        # "Analyze this function") do not name a project and are
        # unaffected. Review-style project requests keep their dedicated
        # chain (Project Analyzer -> Reviewer), so "review" is not
        # included here.
        names_project = bool(
            re.search(r"\b(project|codebase|repo|repository)\b", low)
        )
        has_project = bool(
            self._project_root(raw_task or "")
            or self._active.get("project_root")
        )
        if (
            names_project
            and has_project
            and not re.search(
                r"\b(code|python|java|javascript|typescript|script|function|file)\b",
                low,
            )
            and re.search(r"\b(analy[sz]e|inspect|examine|audit|evaluate)\b", low)
        ):
            return "project"

        # "Add comments" / "Add README" are documentation work, not code.
        # Anchored to the START of the request: pasted code or the
        # attached project's file list can legitimately contain "add"
        # (e.g. def add(...)) and "README.md" later in the message, so an
        # unanchored scan would misroute "Analyze this Python code:
        # ```python def add(...)``` [Attached project ... README.md]" to
        # Documentation instead of Code Analysis.
        if re.search(
            r"^\s*\badd\b.*\b(comments?|docstrings?|readme|documentation|docs)\b",
            low,
        ):
            return "documentation"
        for pattern, target in self._FOLLOWUP_VERB_OVERRIDES:
            if re.search(pattern, low):
                if target == "coding" and not self._code_work_followup(low):
                    # Prose-style follow-ups ("Rewrite it for an
                    # experienced programmer", "Improve the explanation")
                    # describe/continue the CONVERSATION, not code: only
                    # pin to the Coding Agent when real code is in
                    # context or the message names code work. Otherwise
                    # let the LLM decision (chat/docs) stand.
                    break
                return target
        # Explain/document follow-ups describe the existing CODE when real
        # code is in context ("Explain it", "Explain the above code",
        # "Generate README"); on a conversational topic they stay Chat.
        if (
            re.search(
                r"\b(explain|describe|document|summarize|elaborate|clarify|comment|readme|generate documentation)\b",
                low,
            )
            and (self._active_has_real_code() or self._has_current_attachment(task))
        ):
            return "documentation"
        # Downgrade: an explain-style follow-up that the LLM sent to
        # Documentation, but which describes a CONVERSATIONAL topic (no
        # real code in context - e.g. "Explain it with an example" after
        # "What is AI?"), must be answered conversationally by Chat, not
        # forced through the documentation agent.
        if (
            decision == "documentation"
            and re.search(
                r"\b(explain|describe|summarize|elaborate|clarify)\b",
                low,
            )
            and not self._active_has_real_code()
            and not self._has_current_attachment(task)
        ):
            return "chat"
        return decision

    # Single-word subjects that always describe the ACTIVE work rather
    # than a new topic: "Explain the architecture/performance/complexity"
    # of what was just built, even though each is only one word.
    _GENERIC_WORK_WORDS = {
        "architecture", "structure", "design", "overview", "summary",
        "details", "detail", "implementation", "performance", "complexity",
        "solution", "error", "interface", "database", "schema",
        "relationships", "dependencies", "optimization", "concept",
        "topic", "subject", "codebase", "module", "feature", "docs",
    }

    @classmethod
    def _subject_words(cls, low):
        """Substantive words left after the leading verb/article are
        stripped - the candidate new subject of a verb-led phrase."""
        t = re.sub(r"^(?:please|can you|could you|hey|ok)\s+", "", low)
        t = re.sub(
            r"^(?:explain|describe|document|review|analy[sz]e|summarize|give|"
            r"compare|show|tell|define|list|write|build|create|make|generate|"
            r"what is|what are|what's|convert|translate|improve|optimize|debug|"
            r"fix|add|deploy|elaborate|continue|run|test|find|normalize|suggest)\b"
            r"[\s:-]*",
            "",
            t,
        )
        t = re.sub(r"^(?:the |this |that |my |our |a |an )+", "", t)
        words = [w.strip(".?!,;:'\"") for w in t.split()]
        return [w for w in words if w and w not in cls._NON_SUBJECT_WORDS]

    @classmethod
    def _has_new_subject(cls, low):
        """True when a verb-led phrase names a fresh subject ("Explain
        Operating System") instead of just pointing back ("Explain it in
        simple words")."""
        return len(cls._subject_words(low)) >= 2

    def _subject_refers_to_active(self, task, subject):
        """Whether a subject continues the active context.

        True when the current message carries a fresh attachment (the
        subject IS the uploaded file), ANY subject word is generic
        work vocabulary ("architecture", "performance", "complexity"...)
        - so "the time complexity" after generated code refers back to
        that code - or a subject word matches the active topic.
        """
        if self._has_current_attachment(task):
            return True
        if any(w in self._GENERIC_WORK_WORDS for w in subject):
            return True
        topic = (self._active.get("topic") or "").lower()
        return bool(topic and any(w in topic or topic in w for w in subject))

    @staticmethod
    def _has_current_attachment(task):
        """True when the current user message itself carries an attached
        file/project marker (so its subject is the attachment, even on
        the very first turn before active context is populated)."""
        return bool(
            re.search(
                r"\[(?:Attached|Uploaded) (?:file|project):",
                task or "",
                re.IGNORECASE,
            )
        )

    @staticmethod
    def _active_topic_for(task):
        """Compact subject phrase for a self-contained request."""
        t = CoordinatorAgent._strip_app_context(task).lower()
        t = re.sub(
            r"^(?:can you|could you|please|kindly|hey|hi|hello|ok)\s+", "", t
        )
        t = re.sub(
            r"^(?:write|build|create|generate|develop|make|design|implement|"
            r"explain|describe|analy[sz]e|review|optimize|refactor|improve|"
            r"debug|fix|document|summarize|convert|show|tell|give|what is|"
            r"what are|what's|define|compare|list|outline|plan|help me)\b"
            r"[\s:-]*",
            "",
            t,
        )
        words = re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)*", t)
        return " ".join(words[:6]) or "current topic"

    @staticmethod
    def _strip_previous_turn_blocks(task):
        """Cut the previous turn's code/response blocks from a request.

        The UI appends "[Previously generated code]" and "[Previous
        assistant response]" after every message; for a brand-new topic
        those describe the OLD subject and must not reach the agent.
        """
        low = task or ""
        for marker in ("[Previously generated code]", "[Previous assistant response]"):
            i = low.find(marker)
            if i != -1:
                low = low[:i].rstrip()
        return low

    def _active_context_block(self, task):
        """Build the context block appended to follow-up prompts.

        Memory priority: uploaded file (already inlined by the UI),
        then active workflow, then the previously generated code - and
        only the active topic/names when the code is already present.
        """
        active = self._active
        parts = []
        if active.get("topic"):
            parts.append(f"Active topic: {active['topic']}")
        if active.get("workflow"):
            parts.append(f"Active application workflow: {active['workflow']}")
        if active.get("project_files"):
            parts.append(
                "Generated application files: " + ", ".join(active["project_files"])
            )
        if active.get("files"):
            parts.append("Uploaded files: " + ", ".join(active["files"]))
        code = active.get("code")
        if (
            code
            and "[Previously generated code]" not in (task or "")
            and "[Attached file:" not in (task or "")
        ):
            parts.append(f"[Previously generated code]\n{code[:1500]}")
        if not parts:
            return None
        return "[Active context]\n" + "\n".join(parts)

    @staticmethod
    def _looks_like_code(text):
        """Whether a response is primarily CODE (generated by a coding
        agent), not prose that merely contains a short inline example.

        Chat answers often include a 3-5 line illustration ("def
        greet(): ...") - that must NOT mark the conversation as code
        context, or explain follow-ups would wrongly upgrade to the
        Documentation Agent. Only substantial code counts: a long
        fenced block, or a body starting with code constructs that is
        large enough to be real output."""
        t = (text or "").strip()
        if not t:
            return False
        if t.startswith(("def ", "class ", "import ", "from ", "async def", "FILE:")) \
                and len(t) > 200:
            return True
        # A fenced block of meaningful size (not a 3-line illustration).
        m = re.search(r"```(?:python)?\s*\n(.*?)```", text or "", re.DOTALL)
        if m and len(m.group(1)) > 200:
            return True
        # Several consecutive code-ish lines without prose around them.
        if t.startswith(("def ", "class ", "import ", "from ", "async def")) \
                and t.count("\n") >= 12:
            return True
        # Non-Python output (Java/C/JS/Go/Rust...) is still CODE: a model
        # may answer a "write Python" request in the wrong language, and
        # the conversation must keep the code context so follow-ups
        # ("Explain the above code", "Review it") route to the code
        # agents instead of losing the context.
        if len(t) > 200:
            code_ish = sum(
                1
                for line in t.splitlines()[:80]
                if re.match(
                    r"^\s*(?:public|private|protected|static|package|import "
                    r"java|#include|int main|func |fn |const |let |var |"
                    r"using |namespace |class |interface |struct |enum |"
                    r"def |async def|from |if |for |while |return |"
                    r"[}\]\];]\s*$)",
                    line,
                )
                or line.rstrip().endswith(("{", "}", ";"))
            )
            if code_ish >= 8:
                return True
        return False

    def _update_active(self, task, followup, result):
        """Persist the current conversation state after a turn."""
        active = self._active
        plain = self._strip_app_context(task)
        if followup == "new_topic":
            active["topic"] = self._active_topic_for(plain)
            active["code"] = None
            active["workflow"] = None

        files = re.findall(
            r"\[(?:Attached|Uploaded) file: ([^\]]*)\]", task, re.IGNORECASE
        )
        projects = re.findall(
            r"\[(?:Attached|Uploaded) project: ([^\]]*)\]", task, re.IGNORECASE
        )
        active["files"] = [
            f.strip() for f in files + [f"project: {p}" for p in projects]
            if f.strip()
        ]
        active["project_root"] = self._project_root(task) or active.get("project_root")

        code = result.get("code") or ""
        if code:
            active["code"] = code[:4000]
        elif followup == "new_topic" and self._looks_like_code(result.get("response", "")):
            active["code"] = self.clean_code_output(result["response"])[:4000]

        if result.get("workflow"):
            wf = result["workflow"]
            active["workflow"] = (
                wf.get("label") or wf.get("type") or "application"
                if isinstance(wf, dict) else str(wf)
            )
        elif followup == "new_topic":
            active["workflow"] = None

        # A generated application becomes the CURRENT PROJECT context:
        # its files stay available for follow-ups ("Review it", "Add
        # Login Module", "Generate REST API documentation") so the user
        # never has to re-provide the project.
        if code and active.get("workflow"):
            files = re.findall(r"^FILE:\s*(.+)$", code, re.MULTILINE)
            names = [f.strip() for f in files if f.strip()]
            if names:
                active["project_files"] = names
            elif active["workflow"]:
                # Single-file or code-only workflow output: keep a
                # descriptive placeholder so project-aware follow-ups know
                # a generated project exists.
                active["project_files"] = [
                    re.sub(r"[^a-z0-9]+", "_", active["workflow"].lower()).strip("_") + ".py"
                ]
        elif followup == "new_topic":
            active["project_files"] = []

        active["last_response"] = (result.get("response") or "")[:800]

    def _enforce_word_count(self, response, target, exact=False):
        """Bring a prose response to an explicit word-count request.

        ``exact`` (user said "exactly N words") is enforced strictly:
        up to three corrective LLM passes with a tight acceptance band,
        keeping the closest attempt. Non-exact requests allow the usual
        plus/minus-five-word band. Code responses are left alone because
        word counts apply to explanations, not code.
        """
        if not response or "```" in response or self._looks_like_code(response):
            return response
        if exact:
            tolerance = 2
            lo, hi = max(1, target - 2), target + 2
            passes = 3
            word_phrase = f"EXACTLY {target}"
        else:
            tolerance = max(5, int(target * 0.1))
            lo, hi = max(5, target - 5), target + 5
            passes = 2
            word_phrase = f"approximately {target}"
        count = count_words(response)
        if abs(count - target) <= tolerance:
            return response
        current = response
        current_count = count
        for _ in range(passes):
            if not self.guard.can_call():
                break
            self.guard.register_call()
            try:
                prompt = (
                    f"The user asked for {word_phrase} words. The response "
                    f"below is {current_count} words - it must be rewritten "
                    f"to between {lo} and {hi} words. Keep every key point; "
                    f"only adjust the length. Count the words carefully "
                    f"before replying and report nothing but the text."
                    f"\n\n{current}"
                )
                corrected = self.model.ask(prompt).strip()
                new_count = count_words(corrected or "")
                if lo <= new_count <= hi:
                    return corrected
                if abs(new_count - target) < abs(current_count - target):
                    current, current_count = corrected, new_count
            except Exception:
                break
        return current

    def _validate_response(self, task, result, followup, directives):
        """Lightweight pre-delivery validation (logs only - never blocks).

        Mirrors the response-quality checklist: right agent, context
        preserved, word count honored, no unrelated context injected.
        """
        checks = [f"agent={result.get('agent', '?')}", f"followup={followup}"]
        if directives.get("word_count"):
            n = count_words(result.get("response", ""))
            checks.append(f"words={n}/~{directives['word_count']}")
        checks.append(f"active_context={'yes' if followup == 'followup' else 'no'}")
        if "[Attached file:" in (task or ""):
            checks.append("upload_included=yes")
        logger.info("Validation: %s", "; ".join(checks))

    def _finish(self, task, response, agent_name, extra=None, memory_message=None):
        """Store the turn in short-term memory and build the result dict."""
        assistant = memory_message if memory_message is not None else response
        self.short_memory.add("user", task)
        # Long workflow responses are summarized so they don't bloat the
        # conversation window injected into future prompts.
        self.short_memory.add("assistant", assistant)
        try:
            self.entity_memory.update_from_turn(
                task, assistant, model=self.model, use_llm=self.guard.can_call()
            )
            self.summary_memory.update(task, assistant, model=self.model)
        except Exception:
            pass

        result = {
            "response": response,
            "agent": agent_name,
        }
        if extra:
            result.update(extra)
        return result

    def generate_test_input(self, code):
        prompt = f"""
You are generating test inputs for a Python program.

Rules:
- Return ONLY the input values.
- Do NOT explain anything.
- Do NOT use markdown.
- One input per line.
- Use realistic values.
- If the program asks for a positive integer, use 10.
- If it asks for yes/no after execution, use no.
- Never return 0 unless the program specifically requires it.

Python Program:

{code}
"""

        response = self.model.ask(prompt)
        response = response.replace("```", "").strip()
        return response

    # =====================================================================
    # Main entry point
    # =====================================================================
    def handle_task(self, task, progress_callback=None):
        """Route a user request through the LangGraph execution graph.

        The Decision Engine classifies intent, the graph dispatches to
        the correct agent node (reusing this coordinator's handlers) and
        the result keeps the exact same shape as before.
        """
        self.guard.reset()
        logger.info(f"User Request: {task}")
        print(f"Task: {task}")

        # Milestone 5 - response quality + intelligent follow-up:
        # 1) resolve terse follow-ups against the active conversation
        #    context (topic / generated code / uploaded files / workflow),
        # 2) attach any explicit response directives (word count, style,
        #    format ...) so the selected agent honors them.
        # Project-level request with no uploaded project / generated-code
        # context: never scan the assistant's own workspace. Ask for the
        # project files instead (a later upload re-enters the normal flow).
        if self._missing_project_context(task):
            logger.info(
                "Project request without project context - requesting upload"
            )
            return self._finish(task, self.NO_PROJECT_MESSAGE, "Assistant")

        directives = extract_directives(task)
        followup = self._classify_followup(task)
        enriched = task
        if followup == "new_topic":
            # A brand-new topic must start a fresh reasoning path: drop
            # the previous turn's code/response blocks the UI appends so
            # they never bleed into the new subject. Attachments of the
            # CURRENT message are kept.
            enriched = self._strip_previous_turn_blocks(task)
        block = self._active_context_block(enriched)
        if followup == "followup" and block:
            enriched = enriched + "\n\n" + block
        # Uploaded-project awareness: when a follow-up acts on an extracted
        # ZIP project (structure / review / analyze / docs / README / bug
        # fixes), inject the project's ACTUAL structure AND its source files
        # so the agents answer from the real code instead of guessing or
        # claiming "no code found". The root comes from the CURRENT message
        # marker first - on the very first turn after a ZIP upload the
        # active context is not populated yet (it is only stored after the
        # graph completes), so relying on _active alone made the first
        # request analyze the app's own workspace.
        proot = self._project_root(enriched) or self._active.get("project_root")
        if (
            followup == "followup"
            and proot
            and re.search(
                r"\b(project|structure|architecture|review|analy[sz]e|readme|"
                r"documentation|docs|api|codebase|files|bug|bugs|fix|debug|"
                r"error|issue)\b",
                self._strip_app_context(task),
                re.IGNORECASE,
            )
        ):
            sblock = self._project_structure_block(proot)
            if sblock:
                enriched = enriched + "\n\n[Uploaded project structure]\n" + sblock
            # The actual source files power code-facing agents (debugging /
            # coding / docs / planning) so "fix the bug in this project"
            # yields corrected code instead of a generic answer. Bounded to
            # keep follow-up prompts within the provider's token budget.
            sources = self._collect_project_sources(
                proot, max_files=8, max_chars=15000
            )
            if sources:
                enriched = enriched + "\n\n[Uploaded project sources]\n" + sources
        req_block = directives_block(directives)
        if req_block:
            enriched += "\n\n" + req_block

        # Follow-up explain requests on existing CODE describe that code:
        # prefer the Documentation Agent over generic chat. The upgrade is
        # deliberately limited to real code context (generated code,
        # uploaded files) - an explain follow-up on a general chat topic
        # ("Explain it with an example" after "What is AI?") stays in
        # Chat, because the Documentation Agent would force it into a
        # documentation template.
        decision = self.decision_engine.decide(enriched)
        stripped = self._strip_app_context(task)
        # Deterministic follow-up routing: terse follow-up verbs on an
        # active context always act on the existing work, so they must
        # never be misrouted by the LLM classifier (e.g. "Optimize it"
        # sent to Documentation, "Find bugs" sent to Chat).
        decision = self._override_followup_decision(
            stripped, followup, decision, raw_task=task
        )
        # Follow-up explain requests on existing CODE describe that code:
        # prefer the Documentation Agent over generic chat. The upgrade is
        # deliberately limited to real code context (generated code,
        # uploaded files) - an explain follow-up on a general chat topic
        # ("Explain it with an example" after "What is AI?") stays in
        # Chat, because the Documentation Agent would force it into a
        # documentation template.
        if (
            followup == "followup"
            and decision == "chat"
            and (self._active_has_real_code() or self._has_current_attachment(enriched))
            and self.EXPLAIN_REQUEST_RE.search(stripped)
        ):
            decision = "documentation"

        # Rich context: rolling summary + user entities + recent turns
        # (follow-up intelligence comes from this block).
        context = self.context_builder.build()

        if self.graph is None:
            from agents.graph import build_graph
            self.graph = build_graph(self)

        state = self.graph.invoke(
            {
                "task": enriched,
                "context": context,
                "decision": decision,
                "progress": progress_callback,
            }
        )

        result = {
            "response": state.get("response", ""),
            "agent": state.get("agent", "Assistant"),
        }
        for key in ("workflow", "code"):
            if state.get(key):
                result[key] = state[key]

        # Milestone 5 - keep the active conversation context in sync and
        # enforce explicit response-quality requirements before returning.
        self._update_active(task, followup, result)
        if directives.get("word_count"):
            result["response"] = self._enforce_word_count(
                result.get("response", ""),
                directives["word_count"],
                exact=bool(directives.get("word_count_exact")),
            )
        self._validate_response(task, result, followup, directives)

        # Long workflow responses store a short memory entry so the next
        # turn's context stays small but still coherent.
        if state.get("memory_message"):
            assistant = state["memory_message"]
            self.short_memory.add("user", task)
            self.short_memory.add("assistant", assistant)
            try:
                self.entity_memory.update_from_turn(
                    task, assistant, model=self.model,
                    use_llm=self.guard.can_call(),
                )
                self.summary_memory.update(task, assistant, model=self.model)
            except Exception:
                pass

        return result

    # =====================================================================
    # Memory handlers
    # =====================================================================
    def _extract_fact(self, task):
        if not self.guard.can_call():
            return None
        self.guard.register_call()

        prompt = f"""
The user shared personal information.
Extract it as a single line in the format:

topic = value

Examples:
"My name is Muskan"      -> name = Muskan
"I like pizza"           -> favorite food = pizza
"I was born in 2001"     -> birth year = 2001

User message:
{task}

Return ONLY that single line.
"""
        try:
            return self.model.ask(prompt).strip()
        except Exception:
            return None

    @staticmethod
    def _split_fact(fact):
        if "=" in fact:
            topic, value = fact.split("=", 1)
            return topic.strip().strip('"').lower(), value.strip().strip('"')
        return "note", fact.strip()

    def _handle_memory_store(self, task):
        agent_name = "Memory Store"
        fact = self._extract_fact(task)

        if fact:
            topic, value = self._split_fact(fact)
            self.short_memory.store_fact(topic, value)
            logger.info(f"Stored fact: {topic} = {value}")

        return self._finish(
            task,
            "Okay, I've stored that information. ✅",
            agent_name,
        )

    def _handle_memory_recall(self, task):
        agent_name = "Memory Recall"
        facts = self.short_memory.get_facts()

        if not facts:
            response = (
                "I don't have any stored information about you yet. "
                "Tell me something about yourself and I'll remember it."
            )
            return self._finish(task, response, agent_name)

        matches = self.short_memory.recall(task)

        if not matches:
            known = "; ".join(f"{k}: {v}" for k, v in facts.items())
            response = (
                "I remember some things about you, but nothing matching "
                f"that question. Here's what I know: {known}"
            )
            return self._finish(task, response, agent_name)

        lines = []
        for topic, value in matches.items():
            if topic.lower() == "name":
                lines.append(f"Your name is {value}.")
            else:
                lines.append(f"Your {topic} is {value}.")

        response = " ".join(lines)
        return self._finish(task, response, agent_name)

    # =====================================================================
    # Chat handler
    # =====================================================================
    def _handle_chat(self, task, context):
        logger.info("Routing -> Chat Agent")
        context = self._augment_with_rag(task, context)
        response = self.chat.answer(task, context)
        return self._finish(task, response, "Chat Assistant")

    # =====================================================================
    # Rich context (follow-up intelligence + project awareness)
    # =====================================================================
    def _retrieve_context(self, task, top_k=3):
        """Lazily build the project vector index and retrieve context."""
        try:
            if self._retriever is None:
                from rag.indexer import VectorIndex
                from rag.retriever import RetrievalChain

                idx = VectorIndex()
                idx.index_directory(
                    ".",
                    skip_dirs={
                        ".git", "venv", "__pycache__", "node_modules",
                        "user_data", "logs", "templates", "assets",
                        # Internal memory state (JSON dumps, shared memory)
                        # is not project knowledge - keep it out of RAG.
                        "memory",
                    },
                )
                self._retriever = RetrievalChain(index=idx, model=self.model)
            history = self.short_memory.get_messages()
            return self._retriever.index.context_for(
                task, top_k=top_k, history=history
            )
        except Exception:
            return ""

    def _augment_with_rag(self, task, context):
        """Append retrieved project context to a handler's context."""
        if "Relevant project context" in (context or ""):
            return context
        rag = self._retrieve_context(task)
        if not rag:
            return context
        return f"{context}\n\n## Relevant project context\n\n{rag}"

    def _is_coding_followup(self, task=""):
        """
        True when the last assistant turn already contains generated code
        AND the current request is a terse relative follow-up ("Optimize
        it", "make it async", "add error handling").

        Follow-ups refer to code the assistant just produced, which is
        already in short-term memory (``Previous Conversation``).
        Injecting retrieved project files on top of that is not just
        redundant - the model can latch onto an unrelated project file
        (e.g. a code-metrics module) and echo it back instead of
        updating the user's code. Skip RAG in that case.

        A FRESH coding request ("Write a fibonacci function") right after
        a workflow keeps RAG: the prior code is context for the model,
        but project awareness is still useful for new work.
        """
        has_code_before = False
        for m in reversed(self.short_memory.get_messages()):
            if m.get("role") != "assistant":
                continue
            last = m.get("message", "") or ""
            if len(last) < 20:
                continue
            has_code_before = bool(
                re.search(r"\bdef \w+\s*\(", last)
                or re.search(r"\bclass \w+", last)
                or re.search(r"```(?:python)?\s*", last)
                or re.search(r"\bimport \w+", last)
            )
            break
        if not has_code_before:
            return False

        # Relative follow-up markers: no new subject, just a verb that
        # refers back to the code ("it", "this", "the code", etc.).
        low = (task or "").strip().lower()
        relative_markers = (
            " it", " its", "this", "that", "the code", "the function",
            "the program", "the app", "the script", "the class",
            "the file", "the solution", "above", "optimize", "refactor",
            "improve", "rewrite", "enhance", "async", "convert",
            "add error", "add check", "add validation", "fix it",
            "make it", "clean it", "simplify", "shorten", "speed up",
        )
        if not low:
            return False
        return any(marker in low for marker in relative_markers)

    def note_uploaded_file(self, name):
        """Remember an uploaded file as part of the user's project context."""
        try:
            self.entity_memory.add("project", os.path.basename(str(name)))
        except Exception:
            pass

    # =====================================================================
    # Code Analysis handler
    # =====================================================================
    def _handle_project(self, task, context=""):
        """Analyze the CURRENT project: an extracted uploaded ZIP when one
        is attached (or kept as the active project). Never falls back to
        the assistant's own workspace - without a project it asks the
        user to upload one."""
        agent_name = "Project Analyzer"
        root = self._project_root(task) or self._active.get("project_root")
        if not root or not os.path.isdir(root):
            return self._finish(task, self.NO_PROJECT_MESSAGE, agent_name)
        report = self.project_analyzer.analyze_project(root)
        return self._finish(task, report, agent_name)

    def _handle_code_analysis(self, task, context):
        """
        Analyze EXISTING code - never generate or modify it.

        Code may come from:
        - an uploaded file (the UI appends "Uploaded File:")
        - a filename mentioned in the request (read from disk)
        - raw code pasted directly in the message
        """
        agent_name = "Code Analysis Agent"
        code = self._extract_code_for_analysis(task, context, self._active)

        if not code:
            response = (
                "I'd love to analyze your code, but I couldn't find any "
                "code in your message. You can:\n"
                "1. Upload a Python file and ask me to analyze it\n"
                "2. Paste the code directly in your message\n"
                "3. Mention a file that already exists, e.g. "
                "\"Analyze agents/coordinator.py\""
            )
            return self._finish(task, response, agent_name)

        # The deterministic static-metrics block stays hidden unless the
        # user explicitly asks for it - normal responses show the clean
        # LLM analysis only.
        include_metrics = bool(self.METRICS_REQUEST_RE.search(task))
        response = self.code_analysis.analyze(
            code, context, include_metrics=include_metrics
        )
        return self._finish(task, response, agent_name)

    def _handle_review(self, task, context):
        """Dedicated Reviewer Agent for "review this code" follow-ups.

        Extracts the code under review (uploaded file, generated code or
        conversation context) and runs the reviewer on it.
        """
        agent_name = "Reviewer Agent"
        code = self._extract_code_for_analysis(task, context, self._active)
        if not code:
            response = (
                "I'd love to review your code, but I couldn't find any "
                "code in your message. You can:\n"
                "1. Upload a Python file and ask me to review it\n"
                "2. Paste the code directly in your message\n"
                "3. Mention a file that already exists, e.g. "
                "\"Review agents/coordinator.py\""
            )
            return self._finish(task, response, agent_name)
        response = self.reviewer.review(code)
        return self._finish(task, response, agent_name)

    @staticmethod
    def _extract_code_for_analysis(task, context="", active=None):
        """
        Best-effort extraction of code from a user request.
        Returns None when no code could be found.

        ``context`` holds the previous conversation, so follow-up
        requests like "analyze this function" can still find code
        the assistant just generated (it lives in the prior turns).
        """
        # 1) Uploaded file content (the UI inlines it after a marker)
        #    and previously generated code carried into follow-ups.
        for marker in (
            "[Attached file: ", "[Uploaded File: ", "Uploaded File:",
            "[Previously generated code]",
        ):
            if marker in task:
                tail = task.split(marker, 1)[1]
                # Strip the filename line (e.g. "app.py\n") - keep the code.
                first_line, sep, rest = tail.partition("\n")
                body = rest.strip() if (sep and rest.strip()) else tail.strip()
                # Stop at the next inlined section so the extracted code
                # is exactly the file/code of interest and never bleeds
                # into the following context blocks (other attachments or
                # the previously generated code).
                for stop in (
                    "\n\n[Attached file: ", "\n\n[Uploaded File: ",
                    "\n\n[Previously generated code]",
                    "\n\n[Previous assistant response]",
                ):
                    if stop in body:
                        body = body.split(stop, 1)[0].strip()
                return body

        # 2) A project attached to the CURRENT message ("Analyze the
        #    project" right after a ZIP upload): analyze the actual
        #    extracted sources - a fresh attachment is the subject of the
        #    message and must never lose to older conversation code.
        proot_here = CoordinatorAgent._project_root(task)
        if proot_here and os.path.isdir(proot_here):
            return CoordinatorAgent._collect_project_sources(proot_here)

        # 3) Markdown code fences
        fence = re.search(r"```(?:python)?\s*\n(.*?)```", task, re.DOTALL)
        if fence:
            return fence.group(1).strip()

        # 4) A filename mentioned in the request that exists on disk
        filename = CoordinatorAgent._extract_filename(task)
        if filename and FileTool.exists(filename):
            return FileTool.read_file(filename)

        # 5) Raw code pasted directly (starts with code-ish prefixes)
        stripped = task.strip()
        if stripped.startswith(("def ", "class ", "import ", "from ", "print(", "async def")):
            return stripped

        # 6) Inline code after a colon: "Analyze this code: print('x')"
        for sep in (":\n", ": "):
            if sep in task:
                tail = task.split(sep, 1)[1].strip()
                if tail.startswith(("def ", "class ", "import ", "from ", "print(", "async def")):
                    return tail

        # 7) Active uploaded project: a follow-up on an extracted ZIP
        #    ("Review it", "Analyze it", "Explain this project") should
        #    operate on the project's actual source files instead of
        #    older conversation code or "I couldn't find any code".
        #    Checked BEFORE the conversation-context fallback so stale
        #    generated code from earlier turns can never win over the
        #    uploaded project.
        root = (active or {}).get("project_root")
        if root and os.path.isdir(root):
            return CoordinatorAgent._collect_project_sources(root)

        # 8) Follow-up code from the previous conversation. The task
        #    itself carries no code ("Analyze this function"), but the
        #    just-generated code is in the recent-conversation block
        #    (prefixed with "Assistant: "). Scope the search to that
        #    section so summary/entity prose mentioning "def foo()" can
        #    never be mistaken for real code. Prefer the most recent
        #    fenced block, then the most recent def/class block, cut at
        #    the next turn marker or section header.
        if context:
            recent = context
            m_sec = re.search(r"## Recent conversation", recent)
            if m_sec:
                recent = recent[m_sec.end():]

            fences = list(
                re.finditer(r"```(?:python)?\s*\n(.*?)```", recent, re.DOTALL)
            )
            if fences:
                return fences[-1].group(1).strip()

            matches = list(
                re.finditer(r"(?<!\w)((?:async )?def \w+\s*\(|class \w+)", recent)
            )
            if matches:
                m = matches[-1]
                tail = recent[m.start(1):]
                cut = re.search(r"\n\s*(?:User|Assistant)\s*:|\n\s*## ", tail)
                if cut:
                    tail = tail[:cut.start()]
                return tail.strip()

        return None

    @staticmethod
    def _collect_project_sources(root, max_files=8, max_chars=40000):
        """Concatenate the text source files of an extracted project so
        analysis/review agents see the real code. Bounded to keep the
        prompt within the provider's token budget."""
        text_exts = {
            "py", "js", "ts", "jsx", "tsx", "java", "c", "cpp", "cc",
            "h", "hpp", "go", "rs", "rb", "html", "css", "json",
            "md", "txt", "toml", "yaml", "yml",
        }
        files = []
        for dirpath, _dirs, names in os.walk(root):
            for name in sorted(names):
                if len(files) >= max_files:
                    break
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext not in text_exts:
                    continue
                path = os.path.join(dirpath, name)
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except OSError:
                    continue
                rel = os.path.relpath(path, root)
                files.append(f"# ---- {rel} ----\n{content}")
            if len(files) >= max_files:
                break
        if not files:
            return None
        return "\n\n".join(files)[:max_chars]

    # =====================================================================
    # Tool handlers
    # =====================================================================
    GITHUB_ACTION_KEYWORDS = {
        "branches": "branches",
        "branch": "branches",
        "commits": "commits",
        "commit history": "commits",
        "tree": "tree",
        "files": "tree",
        "structure": "tree",
        "stats": "stats",
        "statistics": "stats",
        "languages": "stats",
        "issues": "issues",
        "pull requests": "pull_requests",
        "pull request": "pull_requests",
        "prs": "pull_requests",
        "recent updates": "recent_updates",
        "latest": "recent_updates",
    }

    def _detect_github_action(self, task):
        """Map user phrasing to a GitHub MCP action (defaults to repo_info)."""
        task_lower = task.lower()
        for keyword, action in self.GITHUB_ACTION_KEYWORDS.items():
            if keyword in task_lower:
                return action
        return "repo_info"

    GITHUB_REPO_RE = re.compile(r"([\w.-]+)\s*/\s*([\w.-]+)")

    def _handle_github(self, task):
        agent_name = "GitHub Tool"
        match = self.GITHUB_REPO_RE.search(task)

        if match:
            owner = match.group(1).rstrip(".")
            repo = match.group(2)
            action = self._detect_github_action(task)

            try:
                result = self.github_tool.execute({
                    "action": action,
                    "owner": owner,
                    "repo": repo,
                })
                response = self._format_github_result(action, result, owner, repo)

                ExecutionTracker.log(
                    "GitHubTool",
                    {"action": action, "owner": owner, "repo": repo},
                    "SUCCESS",
                    response,
                )
            except Exception as e:
                response = f"Error fetching repository: {e}"
        else:
            response = (
                "Please provide the repository in owner/repository "
                "format (e.g. tensorflow/tensorflow)."
            )

        return self._finish(task, response, agent_name)

    @staticmethod
    def _format_github_result(action, result, owner, repo):
        """Turn a raw MCP result into readable markdown for the user.

        MCP actions return either a dict (repo_info/stats/recent_updates)
        or a list (branches/commits/tree/issues/pull_requests), so only
        plain strings (error messages) short-circuit here.
        """
        if isinstance(result, str):
            return result

        if action == "repo_info":
            return (
                f"**{result.get('name', owner)}**\n\n"
                f"- ⭐ Stars: {result.get('stars', 0)}\n"
                f"- 🍴 Forks: {result.get('forks', 0)}\n"
                f"- 💻 Language: {result.get('language') or 'N/A'}\n"
                f"- 🐛 Open issues: {result.get('open_issues', 0)}\n"
                f"- 🌿 Default branch: {result.get('default_branch') or 'N/A'}"
            )

        if action == "branches":
            if "error" in result:
                return result["error"]
            lines = [f"**Branches of {owner}/{repo}:**"]
            for b in result:
                lines.append(f"- 🌿 {b['name']}")
            return "\n".join(lines)

        if action == "commits":
            if "error" in result:
                return result["error"]
            lines = [f"**Recent commits of {owner}/{repo}:**"]
            for c in result:
                lines.append(f"- {c['sha']} {c['message']} ({c['author']})")
            return "\n".join(lines)

        if action == "tree":
            if "error" in result:
                return result["error"]
            lines = [f"**Repository tree of {owner}/{repo}:**"]
            for item in result[:50]:
                icon = "📁" if item.get("type") == "tree" else "📄"
                lines.append(f"- {icon} {item['path']}")
            return "\n".join(lines)

        if action == "stats":
            if "error" in result:
                return result["error"]
            languages = result.get("languages") or {}
            lines = [
                f"**Stats for {owner}/{repo}:**",
                f"- ⭐ Stars: {result.get('stars', 0)}",
                f"- 🍴 Forks: {result.get('forks', 0)}",
                f"- 🐛 Open issues: {result.get('open_issues', 0)}",
                f"- 🌐 Languages: {', '.join(languages.keys()) or 'N/A'}",
            ]
            return "\n".join(lines)

        if action == "issues":
            if "error" in result:
                return result["error"]
            lines = [f"**Open issues in {owner}/{repo}:**"]
            for i in result:
                lines.append(f"- #{i['number']} {i['title']}")
            return "\n".join(lines)

        if action == "pull_requests":
            if "error" in result:
                return result["error"]
            lines = [f"**Pull requests in {owner}/{repo}:**"]
            for pr in result:
                lines.append(f"- #{pr['number']} {pr['title']} (@{pr.get('author', '?')})")
            return "\n".join(lines)

        if action == "recent_updates":
            if "error" in result:
                return result["error"]
            lines = [
                f"**Latest updates of {owner}/{repo}:**",
                f"- 📅 Last push: {result.get('pushed_at', 'N/A')}",
            ]
            for c in result.get("recent_commits", []):
                lines.append(f"- {c['sha']} {c['message']} ({c['author']})")
            return "\n".join(lines)

        return str(result)

    def _handle_patch(self, task):
        agent_name = "Patch Tool"

        prompt = f"""
Convert this modification request into patch format.

User request:
{task}

Return ONLY:

PATCH: filename.py

REPLACE:
old code

WITH:
new code
"""

        patch_response = self.coding.solve_task(prompt)
        patches = PatchParser.parse(patch_response)

        if not patches:
            return self._finish(
                task,
                "Could not generate patch instructions.",
                agent_name,
            )

        results = []
        for p in patches:
            try:
                result = PatchTool.apply_patch(
                    p["file"],
                    p["old"],
                    p["new"],
                )
                status = "SUCCESS" if "Patched" in result else "FAILED"
            except Exception as e:
                result = f"Patch error: {e}"
                status = "FAILED"

            results.append(result)
            ExecutionTracker.log(
                "PatchTool",
                {
                    "file": p["file"],
                    "old_length": len(p["old"]),
                    "new_length": len(p["new"]),
                },
                status,
                result,
            )

            validation = ActionValidator.validate_patch(p["file"], p["new"])
            results.append(f"Validation: {validation['message']}")

        return self._finish(task, "\n".join(results), agent_name)

    def _handle_file(self, task):
        agent_name = "File Tool"
        task_lower = task.lower()

        # ------------------------- READ FILE -------------------------
        if any(kw in task_lower for kw in ["read", "show", "open"]):
            filename = self._extract_filename(task)

            if filename is None:
                return self._finish(task, "No filename specified.", agent_name)

            if FileTool.exists(filename):
                content = FileTool.read_file(filename)
                ExecutionTracker.log(
                    "FileTool",
                    {"action": "read", "path": filename},
                    "SUCCESS",
                    content,
                )
                return self._finish(task, content, agent_name)

            return self._finish(task, f"File not found: {filename}", agent_name)

        # ------------------------- DELETE FILE -------------------------
        if "delete" in task_lower:
            filename = self._extract_filename(task)

            if filename is None:
                return self._finish(task, "No filename specified.", agent_name)

            response = FileTool.delete_file(filename)
            ExecutionTracker.log(
                "FileTool",
                {"action": "delete", "path": filename},
                "SUCCESS",
                response,
            )
            return self._finish(task, response, agent_name)

        # ------------------------- UPDATE FILE -------------------------
        # Catch all modification verbs so "change/modify/replace X.py"
        # uses the reliable whole-file regeneration flow below instead
        # of falling through to the CREATE branch.
        if any(kw in task_lower for kw in [
            "update", "change", "modify", "replace", "edit", "append to"
        ]):
            filename = self._extract_filename(task)

            if filename is None or not FileTool.exists(filename):
                return self._finish(task, "File not found.", agent_name)

            if filename in PROTECTED_FILES:
                return self._finish(
                    task,
                    f"❌ {filename} is protected and cannot be modified.",
                    agent_name,
                )

            context = self.short_memory.get_context()
            existing_code = FileTool.read_file(filename)

            prompt = f"""
Previous Conversation:
{context}

Existing File:
{existing_code}

Update Request:
{task}

Return only the complete updated code.
"""

            code = self.clean_code_output(self.coding.solve_task(prompt))
            code = self._unwrap_file_writer(code)
            result = FileTool.write_file(filename, code)
            ExecutionTracker.log(
                "FileTool",
                {"action": "update", "path": filename},
                "SUCCESS",
                result,
            )
            return self._finish(task, f"✅ {filename} updated successfully.", agent_name)

        # ------------------------- CREATE / SAVE FILE -------------------------
        context = self.short_memory.get_context()
        prompt = f"""
The user wants to CREATE a file containing code/content.

Return ONLY the raw content that should be written into the file.

Rules:
- Return the actual code/content the user asked to store.
- NEVER return Python code that opens/writes/closes the file
  (no open(), no file.write(), no file.close()).
- Do not use Markdown code fences.

Previous Conversation:
{context}

Current User Request:
{task}
"""

        code_response = self.coding.solve_task(prompt)
        filename = self._extract_filename(task) or "generated_code.py"

        if filename in PROTECTED_FILES:
            return self._finish(
                task,
                f"❌ {filename} is protected and cannot be overwritten.",
                agent_name,
            )

        code = self.clean_code_output(code_response)
        # Defensive: never store "read-file code"; store the actual content.
        code = self._unwrap_file_writer(code)

        result = FileTool.write_file(filename, code)
        ExecutionTracker.log(
            "FileTool",
            {"action": "write", "path": filename},
            "SUCCESS",
            result,
        )
        return self._finish(task, f"✅ {result}", agent_name)

    @staticmethod
    def _looks_like_code_response(text):
        """True when a coding-agent response actually contains code: a
        fenced block, FILE:/PATCH: action blocks, or code constructs at
        the start of a line. Used to retry coding requests that returned
        prose instead of code."""
        t = text or ""
        if "```" in t or "FILE:" in t or "PATCH:" in t:
            return True
        return bool(
            re.search(
                r"^\s*(def |class |import |from |async def |public |private "
                r"|protected |static |int main|#include|function |const "
                r"|let |var |using |namespace |print\()",
                t,
                re.MULTILINE,
            )
        )

    @staticmethod
    def _unwrap_file_writer(code):
        """
        Defensive unwrap: if the LLM returned a script that WRITES the file
        (open/write/close) instead of the raw content, extract the content
        that was written. This keeps saved files containing the actual code
        rather than "read-file code".

        Only unwraps when the whole response IS a wrapper script (starts
        with file = open( and ends with file.close()) so normal code that
        merely mentions file.write() is never corrupted.
        """
        text = code.strip()
        if not (text.startswith("file = open(") and text.endswith("file.close()")):
            return code
        if len(re.findall(r"file\.write\s*\(", text)) != 1:
            return code

        # Extract the string-literal argument of the single file.write(...)
        # call and decode it with ast.literal_eval, so escaped quotes
        # (file.write("print(\"hi\")")) come out clean instead of saving
        # backslash garbage. Falls back to the raw text when the argument
        # is not a plain literal (e.g. a variable name).
        m = re.search(
            r"file\.write\s*\(\s*((['\"])(?:\\.|(?!\2).)*\2)\s*\)",
            text,
            re.DOTALL,
        )
        if m:
            try:
                return ast.literal_eval(m.group(1))
            except (ValueError, SyntaxError):
                return m.group(1)[1:-1]
        return code

    def _apply_patches_to_context(self, response):
        """Execute PATCH instructions from a coding response and return
        ONLY the resulting code.

        The patch target is resolved in order:
        1. a real file on disk (existing PatchTool behavior),
        2. the in-memory active code of the current conversation, so
           follow-ups like "Optimize the code" produce a working result
           even when the file was never saved.

        Patches that cannot be matched are skipped (existing code is
        kept) and every application is logged through the Execution
        Tracker. The raw PATCH/REPLACE/WITH instructions are never
        returned.
        """
        patches = PatchParser.parse(response)
        if not patches:
            return self.clean_code_output(response)
        result_code = ""
        for p in patches:
            outcome = ""
            status = "FAILED"
            try:
                if os.path.exists(p["file"]):
                    outcome = PatchTool.apply_patch(p["file"], p["old"], p["new"])
                    status = "SUCCESS" if "Patched" in outcome else "FAILED"
                    with open(p["file"], "r", encoding="utf-8") as f:
                        result_code = f.read()
                else:
                    base = result_code or self._active.get("code") or ""
                    if p["old"] and p["old"] in base:
                        result_code = base.replace(p["old"], p["new"])
                        outcome = f"Patched: {p['file']} (in-memory)"
                        status = "SUCCESS"
                    else:
                        result_code = base
                        outcome = "Old code not found in file or active context."
            except Exception as e:
                result_code = result_code or self._active.get("code") or ""
                outcome = f"Patch error: {e}"
            try:
                ExecutionTracker.log(
                    "PatchTool",
                    {
                        "file": p["file"],
                        "old_length": len(p["old"] or ""),
                        "new_length": len(p["new"] or ""),
                    },
                    status,
                    outcome,
                )
            except Exception:
                pass
        return self.clean_code_output(result_code)

    # =====================================================================
    # Coding handler (also handles execution when requested)
    # =====================================================================
    def _handle_coding(self, task, context, decision):
        agent_name = "Coding Agent"
        is_execution = decision == "execution"
        # Follow-ups on just-generated code already carry that code in
        # "Previous Conversation" - skip project-file RAG so the model
        # updates the user's code instead of echoing a project file.
        if not self._is_coding_followup(task):
            context = self._augment_with_rag(task, context)

        prompt = f"""
You are an AI coding assistant.

You can either:

1. Generate full files in EXACTLY this format:

FILE: generated_program.py

print("Hello")

Rules:
- The FILE line must contain ONLY the filename.
- Start the Python code on the NEXT line.
- Never put Python code on the same line as FILE:.
- Do not use Markdown code fences.

Never overwrite:
- app.py
- main.py
- agents/coordinator.py

2. OR return PATCH updates in this format:

PATCH: app.py
REPLACE:
<old code>
WITH:
<new code>

Rules:
- Use FILE format for new files
- Use PATCH format for modifications
- Only output code, no explanation
- Return only raw Python code.
- Do NOT use Markdown.
- Do NOT use ```python or ``` fences.
- Keep the code simple and readable: match the size of the request,
  avoid unnecessary classes, abstractions, patterns, or dependencies.

Previous Conversation:
{context}

User Request:
{task}
"""

        response = self.coding.solve_task(prompt)

        # Safeguard: an explicit code request must produce CODE. The
        # model occasionally answers with prose ("# Please provide the
        # code you would like me to review.") instead of the requested
        # implementation - retry once with a firmer instruction so the
        # user gets working code instead of a dead end. This is the
        # application enforcing the user's request, not a workaround for
        # a specific model.
        if (
            not is_execution
            and not self._looks_like_code_response(response)
            and self.guard.can_call()
        ):
            try:
                retry_prompt = (
                    "The user explicitly asked you to WRITE CODE. Output "
                    "ONLY the complete, working code for their request. "
                    "Do not ask questions and do not add commentary.\n\n"
                    f"User request:\n{task}"
                )
                response = self.coding.solve_task(retry_prompt)
            except Exception:
                pass

        # Pure code request: return ONLY the code. No file saving, no
        # patches, no execution. Tools (File/Patch/Code Executor) stay
        # reserved for explicit execution/file requests.
        if not is_execution:
            if has_patch_instructions(response):
                # The model answered with PATCH instructions instead of a
                # full code dump. Execute them against the active code /
                # file and return ONLY the resulting code - the raw
                # PATCH/REPLACE/WITH block is an internal tool command
                # and must never reach the user.
                code = self._apply_patches_to_context(response)
                return self._finish(task, code, agent_name)
            code = self.clean_code_output(response)
            # Drop any remaining FILE: headers so multi-file responses
            # also display code only, with no "Saved:"/header noise.
            code = "\n".join(
                line for line in code.splitlines()
                if not line.strip().startswith("FILE:")
            ).strip()
            return self._finish(task, code, agent_name)

        extra_lines = []

        # ------------------------- PATCH handling -------------------------
        if "PATCH:" in response:
            patches = PatchParser.parse(response)
            for p in patches:
                try:
                    result = PatchTool.apply_patch(
                        p["file"],
                        p["old"],
                        p["new"],
                    )
                    status = "SUCCESS" if "Patched" in result else "FAILED"
                except Exception as e:
                    result = f"Patch error: {e}"
                    status = "FAILED"

                extra_lines.append(result)
                ExecutionTracker.log(
                    "PatchTool",
                    {
                        "file": p["file"],
                        "old_length": len(p["old"]),
                        "new_length": len(p["new"]),
                    },
                    status,
                    result,
                )

        # ------------------------- MULTI FILE handling -------------------------
        if "FILE:" in response:
            files = MultiFileParser.parse(response)
            safe_files = [
                f for f in files if f["path"] not in PROTECTED_FILES
            ]
            saved = FileTool.write_multiple_files(safe_files)
            for s in saved:
                path = s.replace("Saved: ", "")
                ExecutionTracker.log(
                    "FileTool",
                    {"action": "write", "path": path},
                    "SUCCESS",
                    s,
                )
            extra_lines.extend(saved)

        # Internal tool commands (PATCH/REPLACE/WITH blocks, FILE:
        # headers) were executed above - never display the raw
        # instructions in the final response, only the useful result
        # (code, saved-file lines, execution output). Strip the model
        # output BEFORE appending the execution result so the appended
        # output is never consumed by the stripper.
        display = strip_action_instructions(response)

        # ------------------------- EXECUTION -------------------------
        if is_execution:
            agent_name = "Code Executor"
            code = self.clean_code_output(response)
            user_input = self.generate_test_input(code)

            result = self.coding.use_tool(
                "run python code",
                {"code": code, "user_input": user_input},
            )

            if result.get("success"):
                output = result.get("result")
            else:
                output = result.get("message", "Execution failed.")

            display = (
                f"{display}\n\n"
                "============\n"
                "Execution Output\n"
                "============\n"
                f"{output}"
            )

        if extra_lines:
            display = f"{display}\n\n" + "\n".join(extra_lines)

        return self._finish(task, display, agent_name)
