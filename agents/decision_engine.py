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
        "memory_recall", "workflow", "chat", "code_analysis",
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
    }

    def __init__(self, model=None, guard=None, use_llm=True):
        self.model = model
        self.guard = guard
        self.use_llm = use_llm and model is not None

        # ---------------- keyword lists (fallback) ----------------
        self.code_analysis_keywords = [
            "analyze this code", "analyze the code", "analyze code",
            "analyze this python", "analyze the following code",
            "analyse this code", "analyse the code", "analyse code",
            "review this code", "review the code", "review this python",
            "review this python file", "review this file",
            "review the following", "code review",
            "explain this code", "explain the code",
            "explain this source code", "explain the source code",
            "explain this python", "explain this file",
            "check code quality", "code quality", "code smell",
            "code smells", "quality score", "find issues in this code",
            "find issues in the code", "find issues in this python",
            "audit this code", "inspect this code", "static analysis",
            "code analysis",
            # Terse relative forms used with uploaded/attached files:
            # "analyse it" / "review it" / "explain it" etc. must land
            # here (and NOT on the file tool) when a file is attached.
            # (Deliberately "X it", never bare "X this", so requests like
            # "Analyze this project" still route to project analysis.)
            "analyze it", "analyse it", "review it", "explain it",
            "analyze that", "analyse that", "review that", "explain that",
            "analyze the attached file", "analyse the attached file",
            "review the attached file", "explain the attached file",
            "analyze the uploaded file", "analyse the uploaded file",
            "review the uploaded file", "explain the uploaded file",
        ]
        self.debug_keywords = [
            "debug", "fix", "bug", "error", "traceback", "exception"
        ]
        self.doc_keywords = [
            "explain", "documentation", "document", "comment", "describe"
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
            "compute", "create a function"
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
        ]
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

    # ===================== public API =====================
    def decide(self, task):
        """
        Classify a user request into one of the categories.
        Returns: str (one of self.CATEGORIES)
        """
        # Classify only the user's own words. The UI inlines uploaded file
        # content after a "[Attached file: ...]" marker - that content must
        # not influence routing (e.g. a filename like test.py must not look
        # like an execution request, and file content must not look like a
        # build/debug request). The handlers still receive the full task.
        task_lower = self._strip_attachments(task.lower())

        # Fast path: unambiguous personal-information statements.
        if self.is_memory_recall(task_lower) and not self._mentions_coding(task_lower):
            return "memory_recall"
        if self.is_memory_store(task_lower) and not self._mentions_coding(task_lower):
            return "memory_store"

        # Fast path: modifying an EXISTING file ("update test_demo.py to
        # print goodbye") is far more reliable via the File Tool, which
        # regenerates the file from its current content, than via the
        # brittle patch flow (which needs the exact old code).
        if self.is_file_task(task_lower) and self.is_patch_task(task_lower):
            return "file"

        intent = self._classify_with_llm(task_lower)
        if intent in self.CATEGORIES:
            return intent

        return self._keyword_fallback(task_lower)

    @staticmethod
    def _strip_attachments(task):
        """Remove the UI's attached-file marker and everything after it.

        The marker ("[Attached file: name]\n<content>") is appended by the
        UI when the user attaches a file, so everything from the marker on
        is the file content, not the user's request.
        """
        match = re.search(
            r"\[(?:Attached|Uploaded) file:", task, flags=re.IGNORECASE
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
- code_analysis: user wants EXISTING code analyzed/reviewed/explained/quality-checked
  ("Analyze this code", "Review this Python file", "Check code quality",
   "Find issues in this code", "Explain this source code")
- debug: user wants help fixing an error or bug ("Fix this error", "Why does my code crash?")
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
    def _keyword_fallback(self, task):
        if self.is_github_task(task):
            return "github"
        # Code analysis is checked before project/documentation so
        # "analyze this code" routes here while "analyze this project"
        # still routes to project analysis.
        if self.is_code_analysis_task(task):
            return "code_analysis"
        if self.is_project_task(task):
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
        if self.is_planner_task(task):
            return "planner"
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
