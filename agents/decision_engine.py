import re


class DecisionEngine:
    """
    Intelligent intent detection for user requests (Issues 5 & 13).

    Primary: LLM-based classification (hybrid approach).
    Fallback: keyword / regex based classification when the LLM is
    unavailable or its answer is not a known category.
    """

    CATEGORIES = {
        "github", "project", "debug", "documentation", "planner",
        "execution", "patch", "file", "coding", "memory_store",
        "memory_recall", "workflow", "chat", "code_analysis", "review",
    }

    # Map common LLM synonyms onto canonical categories
    ALIASES = {
        "debugging": "debug",
        "plan": "planner",
        "planning": "planner",
        "docs": "documentation",
        "doc": "documentation",
        "general": "chat",
        "conversation": "chat",
        "conversational": "chat",
        "execute": "execution",
        "run": "execution",
        "memory": "memory_store",
        "remember": "memory_store",
        "github_repo": "github",
        "codeanalysis": "code_analysis",
        "analyze_code": "code_analysis",
        "analysis": "code_analysis",
        "reviewer": "review",
        "code_review": "review",
        "codereview": "review",
    }

    def __init__(self, model=None, guard=None, use_llm=True):
        self.model = model
        self.guard = guard
        self.use_llm = use_llm and model is not None

        # Routing cache (Milestone 4 - performance). Repeated or
        # turn-based phrasing ("review it", "optimize it") is classified
        # once and answered from memory, skipping the LLM classifier call
        # on follow-ups. Size-capped: when full the cache resets, so it
        # can never grow unbounded.
        self._cache = {}
        self._CACHE_MAX = 256

        # ---------------- keyword lists (fallback) ----------------
        self.code_analysis_keywords = [
            "analyze this code", "analyze the code", "analyze code",
            "analyze this python", "analyze the following code",
            "analyse this code", "analyse the code", "analyse code",
            "check code quality", "code quality", "code smell",
            "code smells", "quality score", "find issues in this code",
            "find issues in the code", "find issues in this python",
            "audit this code", "inspect this code", "static analysis",
            "code analysis",
            # Terse relative forms used with uploaded/attached files:
            # "analyse it" / "review it" must land here (and NOT on the
            # file tool) when a file is attached. "explain" is NOT
            # analysis: per the response-quality spec, explain requests
            # route to the Documentation Agent (or Chat when no code is
            # in context). (Deliberately "X it", never bare "X this", so
            # requests like "Analyze this project" still route to project
            # analysis.)
            "analyze it", "analyse it",
            "analyze that", "analyse that",
            "analyze the attached file", "analyse the attached file",
            "analyze the uploaded file", "analyse the uploaded file",
            # Follow-up phrasings on previously generated code / an active
            # application (Milestone 5 - intelligent follow-up).
            "time complexity", "explain time complexity", "space complexity",
            "explain space complexity", "code complexity", "analyze the generated",
            "analyse the generated", "analyze the application",
            "analyse the application", "analyze the generated application",
            "analyze the generated code", "analyze complexity",
        ]
        self.debug_keywords = [
            "debug", "fix", "bug", "error", "traceback", "exception",
            "root cause", "crash"
        ]
        self.doc_keywords = [
            "explain", "documentation", "document", "comment", "describe",
            "readme", "api documentation", "usage guide", "user guide",
            "docstring", "comments",
        ]
        self.planner_keywords = [
            "plan", "planning", "design", "roadmap", "workflow",
            "architecture", "step by step"
        ]
        self.project_keywords = [
            "analyze", "analysis", "project", "structure", "codebase",
            "audit"
        ]
        self.execution_keywords = ["run", "execute", "test", "output"]
        self.patch_keywords = [
            "patch", "modify", "replace", "change", "update"
        ]
        self.file_keywords = [
            "read file", "write file", "delete file", "create file",
            "open file", "save file"
        ]
        self.github_keywords = [
            "github", "repository", "repo", "stars", "forks"
        ]
        # Documentation-GENERATION phrasings must route to the Documentation
        # Agent even when they mention a project ("Generate README for this
        # project") - the intent is docs, not project analysis.
        self.doc_generation_words = [
            "readme", "documentation", "document", "comment", "comments",
            "docstring", "usage guide", "user guide", "api documentation",
        ]
        self.workflow_keywords = [
            "build", "develop", "create an application",
            "create a system", "design a system", "build a system",
            "make an application", "develop an application",
            "develop software", "build software", "software that",
            "application that", "system that", "full stack",
            "web application", "web app", "app that"
        ]
        self.coding_keywords = [
            "write", "code", "program", "script", "function", "class",
            "implement", "generate", "algorithm", "calculate",
            "compute", "create a function",
            # Follow-up verbs: "optimize it", "refactor this", "improve it"
            # must stay in the coding flow so previous context is reused.
            "optimize", "refactor", "improve", "rewrite", "enhance",
            "make it async", "convert it", "convert", "add", "fix",
            "deploy"
        ]
        self.memory_store_patterns = [
            r"\bmy name is\b",
            r"\bmy name's\b",
            r"\bi am\b",
            r"\bi'm\b",
            r"\bi like\b",
            r"\bi love\b",
            r"\bi hate\b",
            r"\bmy favourite\b",
            r"\bmy favorite\b",
            r"\bremember that\b",
            r"\bremember this\b",
            r"\bcall me\b",
            r"\bi was born\b",
            r"\bi work (as|at)\b",
            r"\bi live (in|at)\b",
            r"\bi study\b",
            r"\bi am from\b",
            r"\bmy (age|birthday|city|country|email|phone|hobby|job|pet|dog|cat)\b",
        ]
        self.memory_recall_patterns = [
            r"\bwhat('s| is) my name\b",
            r"\bwhat is my\b",
            r"\bwhat's my\b",
            r"\bwhat are my\b",
            r"\bdo you remember\b",
            r"\bwhat did i (tell|say|share|ask)\b",
            r"\bwho am i\b",
            r"\brecall\b",
            r"\bremember my\b",
            r"\bwhat do you (know|remember) about me\b",
            r"\btell me about myself\b",
            r"\bwho('s| is) my\b",
            r"\bwho('s| is) your\b",
            r"\bwhere('s| is| are) my\b",
            r"\bwhen('s| is) my\b",
            r"\bhow (old|tall) am i\b",
            r"\bwhat('s| is) my favorite\b",
            r"\bwhat('s| is) my favourite\b",
            r"\bwho is my (favorite|favourite|best|closest)\b",
            r"\bdo i (like|prefer|use|enjoy)\b",
            r"\bwhich (programming language|language|framework|tool)\b.*\bdo i\b",
        ]
        # "Which X do I ..." questions about the user's own preferences.
        self.RECALL_ABOUT_ME_RE = re.compile(
            r"\bwhich\b.*\bdo i\b", re.IGNORECASE
        )
        self.chat_patterns = [
            r"^(what|who|why|how|when|where|which|is it|can you)\b",
            r"\bwhat is\b",
            r"\bwhat's\b",
            r"\bwho is\b",
            r"\bwho's\b",
            r"\bdefine\b",
            r"\bexplain\b",
            r"\bdescribe\b",
            r"\btell me about\b",
            r"^(hi|hello|hey|thanks|thank you|good (morning|afternoon|evening))\b",
        ]

    # Chain workflows (Milestone 4 - complex orchestration).
    # Explicit compound requests only - a bare "debug", "review" or
    # "explain" keeps its single-agent routing (backward compatible).
    CHAIN_PATTERNS = {
        # Write Code -> Code Analysis -> Reviewer -> Documentation
        # (checked first: a coding-first compound request must win over
        # the explain_document patterns, which only see the later
        # "review ... and generate documentation" clause).
        "code_review_docs": [
            # write/build ... code ... and then review/debug/analyze/fix/document
            r"^(write|build|create|generate|develop|implement|make)\b.*\b(code|python|java|javascript|function|endpoint|api|script|program|application|app|module)\b.*\b(and|then|also)\b.*\b(review|debug|analy[sz]e|find|fix|improve|document)\b",
            # write/build ... code ..., <verb1> ..., <comma/and>, <verb2> ...
            # (compound pipeline like "..., review it, fix any issues, ...")
            r"^(write|build|create|generate|develop|implement|make)\b.*\b(code|python|java|javascript|function|endpoint|api|script|program|application|app|module)\b.*\b(review|debug|analy[sz]e|find|fix|improve)\b.*\b(,|and|then)\b.*\b(review|debug|analy[sz]e|fix|improve|document|provide|give)\b",
            # write/build ... and then document / generate documentation
            r"^(write|build|create|generate|develop|implement|make)\b.*\b(and|then|also)\b.*\b(document|generate documentation)\b",
        ],
        # Review Project -> Project Analyzer -> Reviewer
        # Review + fix in one request: Project Analyzer -> Reviewer ->
        # Coding. Checked BEFORE the plain review_project patterns so
        # "Review this project and fix the most important bug" runs the
        # full pipeline instead of stopping after the review.
        "review_project_fix": [
            r"review\s+(the\s+|this\s+|my\s+|our\s+)?(entire\s+|whole\s+)?"
            r"(project|codebase|application|app)(?!\s+code).*\b(and|then|also)\b"
            r".*\b(fix|repair|solve|correct)\b",
            # "Review and fix this project" - the fix verb comes before the
            # project noun. The project word must follow the fix verb, so
            # "Review this code and fix it" is NOT pulled into the chain.
            r"\breview\b.*\b(and|then|also)\b.*\b(fix|repair|solve|correct)\b"
            r".*\b(project|codebase|application|app)\b",
            r"\b(fix|repair|solve|correct)\b.*\b(the\s+)?(most\s+)?"
            r"(important\s+|critical\s+|biggest\s+)?(bug|issue|problem|error)\b"
            r".*\b(in|of)\b.*\breview\b.*\b(project|codebase|application|app)\b",
        ],
        "review_project": [
            r"review\s+(the\s+|this\s+|my\s+|our\s+)?(entire\s+|whole\s+)?(project|codebase|application|app)(?!\s+code)",
            r"\bproject\s+review\b",
            r"\breview\s+the\s+(project|codebase|application|app)\s+(architecture|structure|quality|health|overall)",
            r"\b(review|audit)\s+(the\s+)?(entire\s+|whole\s+)?(project|codebase)\s+(for|to|and)",
        ],
        # Debug Code -> Debugger -> Documentation
        "debug_document": [
            r"debug.*\b(and|then|also)\b.*\bdocument",
            r"\bdocument.*\b(and|then|also)\b.*\bdebug",
            r"debug.*\bdocumentation\b",
            r"\bfix\s+(the\s+|this\s+)?(bug|error|issue).*\b(and|then)\b.*\bdocument",
            r"\bdebug\b.*\b(create|write|generate)\b.*\bdocumentation",
        ],
        # Explain Code -> Code Analysis -> Documentation
        "explain_document": [
            r"\b(explain|analy[sz]e|review)\b.*\b(and|then)\b.*\b(generate\s+)?(documentation|document|docs)",
            r"\b(explain|analy[sz]e)\b.*\bdocumentation\b",
            r"\b(explain|analy[sz]e)\b.*\b(generate|write|create)\b.*\bdocs\b",
            r"\b(generate|write|create)\b.*\bdocumentation.*\b(and|then)\b.*\b(explain|analy[sz]e)",
        ],
    }

    def detect_chain(self, task):
        """Return a compound-workflow chain id when the request describes
        a multi-stage workflow (e.g. "review the project", "debug this
        code and document the fix"), else None.

        Only explicit compound phrasing triggers a chain - single-intent
        requests ("debug this", "explain this code") keep their existing
        single-agent routing, so nothing that worked before changes.
        """
        task_lower = self._strip_attachments(task.lower())
        for chain, patterns in self.CHAIN_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, task_lower):
                    return chain
        return None

    # ===================== public API =====================
    def decide(self, task):
        """
        Classify a user request into one of the categories.
        Returns: str (one of self.CATEGORIES)
        """
        task_lower = self._strip_attachments(task.lower())
        cached = self._cache.get(task_lower)
        if cached is not None:
            return cached
        intent = self._decide_uncached(task_lower)
        if len(self._cache) >= self._CACHE_MAX:
            self._cache.clear()
        self._cache[task_lower] = intent
        return intent

    def _decide_uncached(self, task_lower):
        """The actual classification logic (runs on cache misses only).

        ``task_lower`` is already attachment-stripped: the UI inlines
        uploaded file content after a "[Attached file: ...]" marker - that
        content must not influence routing (e.g. a filename like test.py
        must not look like an execution request). The handlers still
        receive the full task.
        """
        # Fast path: unambiguous personal-information statements. Recall
        # questions of the form "Which <language/framework/tool> do I
        # <like/use>?" are about the USER even when a coding word appears
        # ("programming language") - never misroute them to coding.
        if self.is_memory_recall(task_lower) and (
            not self._mentions_coding(task_lower)
            or self.RECALL_ABOUT_ME_RE.search(task_lower)
        ):
            return "memory_recall"
        if self.is_memory_store(task_lower) and not self._mentions_coding(task_lower):
            return "memory_store"

        # Fast path: modifying an EXISTING file ("update test_demo.py to
        # print goodbye") is far more reliable via the File Tool, which
        # regenerates the file from its current content, than via the
        # brittle patch flow (which needs the exact old code).
        if self.is_file_task(task_lower) and self.is_patch_task(task_lower):
            return "file"

        # Fast path: explicit analyze-the-code requests are deterministic.
        # The LLM occasionally maps "Analyze this Python code" onto the
        # documentation examples ("Explain this code") and misroutes it to
        # the Documentation Agent - that is exactly what happened live with
        # a real model. An explicit "analyze" verb with real code evidence
        # must always reach Code Analysis, before the LLM is trusted.
        # "Analyze this project" carries no code evidence, so it is
        # unaffected; review/explain phrasings are deliberately not
        # intercepted here.
        if (
            re.search(r"\banaly[sz]e\b", task_lower)
            and self.is_code_analysis_task(task_lower)
        ):
            return "code_analysis"

        intent = self._classify_with_llm(task_lower)
        if intent in self.CATEGORIES:
            return intent

        return self._keyword_fallback(task_lower)

    @staticmethod
    def _strip_attachments(task):
        """Remove UI/coordinator context blocks appended after the request.

        Everything from the first marker on is context - attached files,
        previously generated code, the active-context block or the
        response-requirements block - never part of the user's intent, so
        routing must ignore it. Markers added since Milestone 5:
        "[Active context]" (coordinator follow-up block) and
        "[Response requirements]" (directive block).
        """
        match = re.search(
            r"\[(?:Attached|Uploaded) (?:file|project):|"
            r"\[Previously generated code\]|\[Previous assistant response\]|"
            r"\[Active context\]|\[Response requirements\]|\[Active task mode:",
            task,
            flags=re.IGNORECASE,
        )
        return task[: match.start()].strip() if match else task

    def _mentions_code_analysis(self, task):
        """
        Detect intent to ANALYZE existing code (not generate/modify it).
        Used to disambiguate "explain/analyze/review <code>" from
        documentation requests and general chat.
        """
        t = task.lower()

        # Explicit phrases win first.
        if any(kw in t for kw in self.code_analysis_keywords):
            return True

        # Heuristic: an analysis verb + evidence that real code is present
        # (a code fence, a .py/.js file mention, or code-ish content).
        analysis_verbs = ["analyze", "analyse", "review", "inspect", "audit", "evaluate", "quality"]
        has_verb = any(v in t for v in analysis_verbs)
        if not has_verb:
            return False

        has_code_evidence = (
            "```" in t
            or bool(re.search(r"\.(py|js|ts|java|c|cpp|go|rs|rb)\b", t))
            or bool(re.search(r"\b(code|script|function|source)\b", t))
        )
        return has_code_evidence


    # ===================== LLM classification =====================
    def _classify_with_llm(self, task):
        if not self.use_llm or self.model is None:
            return None
        if self.guard is not None and not self.guard.can_call():
            return None

        prompt = self._build_classifier_prompt(task)

        try:
            if self.guard is not None:
                self.guard.register_call()
            raw = self.model.ask(prompt)
        except Exception:
            return None

        intent = (raw or "").strip().lower()
        intent = re.sub(r"[^a-z_]", "", intent)
        intent = self.ALIASES.get(intent, intent)
        return intent

    def _build_classifier_prompt(self, task):
        return f"""
You are an intent classifier for an AI coding assistant.

Classify the user's request into EXACTLY ONE of these categories.
Reply with only the category name. Do not add any other text.

Categories:
- memory_store: user shares personal information about themselves to be remembered
  ("My name is Muskan", "I like pizza", "Remember that I have a cat")
- memory_recall: user asks what you remember about them
  ("What is my name?", "Do you remember my favorite color?")
- workflow: user wants to build/develop a complete software application or system
  ("Build a calculator app", "Could you develop software that manages books?")
- coding: user wants code for a specific programming task or algorithm
  ("Write a Python function to find factorial", "Write code to sort a list")
- code_analysis: user wants EXISTING code analyzed/quality-checked, or its
  complexity explained ("Analyze this code", "Check code quality",
   "Find issues in this code", "Analyze it", "Explain time complexity",
   "Explain space complexity")
- review: user wants a code review of existing code ("Review this code",
  "Review it", "Review the generated application", "Code review")
- debug: user wants help fixing an error or bug ("Fix this error", "Why does my code crash?",
  "Find bugs", "Fix it", "Debug it", "Find the root cause")
- documentation: user wants documentation or explanation of code
  ("Document this code", "Explain this code", "Explain this function",
   "Explain it", "Add comments", "Generate README", "Explain in 100 words",
   "Explain the architecture", "Explain line by line")
- coding: user wants code for a specific programming task or algorithm
  ("Write a Python function to find factorial", "Write code to sort a list",
   "Optimize it", "Convert it into Java", "Add Login Module", "Improve the code")

Follow-up requests: a short message that references the previous turn
("it", "this", "above", "the code", "the app") acts on the existing
topic/code - pick the agent that would act on that context (coding
for optimize/convert/add/improve, review for review, code_analysis for
analyze/complexity, documentation for explain/comments/readme, debug
for bugs/errors). A message with a brand-new subject ("Explain
Operating System", "Explain Cloud Computing") is a NEW TOPIC and
should be classified normally.
- documentation: user wants documentation or explanation of code
  ("Document this code", "Explain this function")
- planner: user wants a plan, design, or roadmap, not code
  ("Make a plan for a web app", "What is the architecture?")
- project: user wants analysis of the current project/codebase
  ("Analyze this project", "What files are in the codebase?")
- file: user wants to read, create, write, update, or delete a file
  ("Read app.py", "Create a file called test.py")
- execution: user wants to run or test code ("Run this code", "Execute the program")
- patch: user wants to modify existing code in a file ("Change the greeting in main.py")
- github: user wants GitHub repository information ("Get info about tensorflow/tensorflow")
- chat: general conversation, questions, greetings, concepts
  ("What is AI?", "Who is Alan Turing?", "Hi!", "What is recursion?")

User request:
{task}

Category:
"""

    # ===================== keyword fallback =====================
    # Explicit review phrasings ("review this code", "review it") route
    # to the dedicated Reviewer Agent; "review the project/codebase" is
    # the multi-agent Project Review chain (detected separately).
    REVIEW_PHRASES = (
        "review this code", "review the code", "review the above code",
        "review this python", "review this file", "review it",
        "review that", "review the attached", "review the uploaded",
        "review the generated", "review the application",
        "review the above", "review the following", "code review",
    )

    def is_review_task(self, task):
        t = task.lower()
        if any(p in t for p in self.REVIEW_PHRASES):
            return True
        return bool(
            re.search(r"\breview\b.*\b(code|file|script|application|generated|above)\b", t)
        )

    def _keyword_fallback(self, task):
        if self.is_github_task(task):
            return "github"
        # Code analysis is checked before project/documentation so
        # "analyze this code" routes here while "analyze this project"
        # still routes to project analysis.
        if self.is_review_task(task):
            return "review"
        if self.is_code_analysis_task(task):
            return "code_analysis"
        if (
            self.is_project_task(task)
            and not any(w in task for w in self.doc_generation_words)
            # A BUILD request that merely mentions "project" ("Build a
            # project management app") is a workflow, not project analysis.
            and not self.is_workflow_task(task)
        ):
            return "project"
        # Modification requests that reference an actual file (e.g.
        # "update test_demo.py to print goodbye") route to the File Tool,
        # which regenerates the file from its existing content - far more
        # reliable than the patch flow for whole-file updates.
        if self.is_file_task(task) and self.is_patch_task(task):
            return "file"
        if self.is_patch_task(task):
            return "patch"
        if self.is_file_task(task):
            return "file"
        if self.is_execution_task(task):
            return "execution"
        if self.is_debug_task(task):
            return "debug"
        # Planner is checked BEFORE workflow: "step-by-step plan for
        # building..." and "development plan" must reach the Planner even
        # though "build"/"develop" substring-match the workflow keywords.
        if self.is_planner_task(task):
            return "planner"
        if self.is_workflow_task(task):
            return "workflow"
        # Concept questions like "Explain recursion" are general chat,
        # not documentation requests for a specific piece of code.
        if self.is_documentation_task(task) and not self._mentions_coding(task):
            if self.is_chat_task(task):
                return "chat"
            return "documentation"
        if self.is_documentation_task(task):
            return "documentation"
        # Coding is checked before chat so "How do I write a function..."
        # routes to Coding, not Chat, even in fallback-only mode.
        if self.is_coding_task(task):
            return "coding"
        if self.is_chat_task(task):
            return "chat"
        return "chat"

    # ------------------------- individual checks -------------------------
    def _mentions_coding(self, task):
        return any(word in task for word in self.coding_keywords)

    def is_github_task(self, task):
        return any(word in task for word in self.github_keywords)

    def is_code_analysis_task(self, task):
        return self._mentions_code_analysis(task)

    def is_project_task(self, task):
        return any(word in task for word in self.project_keywords)

    def is_file_task(self, task):
        # Filenames inside attachment markers ("[Attached file: test.py]") are
        # the UI's way of inlining uploaded content - they are NOT requests to
        # operate on a real file on disk, so they must not trigger file routing.
        t = re.sub(
            r"\[Attached file: [^\]]*\]", "", task, flags=re.IGNORECASE
        )
        t = re.sub(r"Uploaded File: [\w.\-]+", "", t, flags=re.IGNORECASE)
        return (
            bool(re.search(r"\b[\w\-]+\.(py|txt|md|json|csv)\b", t))
            or any(word in task for word in self.file_keywords)
        )

    def is_patch_task(self, task):
        return any(word in task for word in self.patch_keywords)

    def is_execution_task(self, task):
        return any(word in task for word in self.execution_keywords)

    def is_debug_task(self, task):
        return any(word in task for word in self.debug_keywords)

    def is_workflow_task(self, task):
        return any(word in task for word in self.workflow_keywords)

    def is_documentation_task(self, task):
        return any(word in task for word in self.doc_keywords)

    def is_planner_task(self, task):
        return any(word in task for word in self.planner_keywords)

    def is_coding_task(self, task):
        return any(word in task for word in self.coding_keywords)

    def is_memory_store(self, task):
        return any(re.search(p, task) for p in self.memory_store_patterns)

    def is_memory_recall(self, task):
        return any(re.search(p, task) for p in self.memory_recall_patterns)

    def is_chat_task(self, task):
        return any(re.search(p, task) for p in self.chat_patterns)
