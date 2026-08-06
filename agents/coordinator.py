import ast
import re

from agents.decision_engine import DecisionEngine
from agents.coding_agent import CodingAgent
from agents.debugging_agent import DebuggingAgent
from agents.documentation_agent import DocumentationAgent
from agents.planner import Planner
from agents.chat_agent import ChatAgent
from agents.project_analyzer_agent import ProjectAnalyzer
from agents.reviewer_agent import ReviewerAgent
from agents.code_analysis_agent import CodeAnalysisAgent

from workflow.workflow_manager import WorkflowManager

from mcp import MCPManager

from tools.code_cleaner import clean_code
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


class CoordinatorAgent:
    """
    Routes user requests to the correct agent / tool / workflow
    based on the Decision Engine's intent classification.
    """

    def __init__(self, model, guard, memory, short_memory):
        # ------------------------- LLM Agents -------------------------
        self.coding = CodingAgent(model, guard)
        self.debugging = DebuggingAgent(model, guard)
        self.docs = DocumentationAgent(model, guard)
        self.chat = ChatAgent(model, guard)
        self.planner = Planner(model, guard)
        self.project_analyzer = ProjectAnalyzer(model, guard)
        self.reviewer = ReviewerAgent(model, guard)
        self.code_analysis = CodeAnalysisAgent(model, guard)

        self.workflow_manager = WorkflowManager(
            self.planner,
            self.coding,
            self.reviewer,
            self.code_analysis,
            self.docs
        )
        self.decision_engine = DecisionEngine(model=model, guard=guard)

        # ------------------------- Core Components -------------------------
        self.model = model
        self.guard = guard
        self.memory = memory
        self.short_memory = short_memory

        # ------------------------- MCP + Tools (Non-LLM) -------------------------
        # All GitHub operations flow through the MCP layer (Task 4/5).
        self.mcp_manager = MCPManager()
        self.github_tool = GitHubTool(mcp=self.mcp_manager)

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

    def _finish(self, task, response, agent_name, extra=None, memory_message=None):
        """Store the turn in short-term memory and build the result dict."""
        self.short_memory.add("user", task)
        # Long workflow responses are summarized so they don't bloat the
        # conversation window injected into future prompts.
        self.short_memory.add(
            "assistant",
            memory_message if memory_message is not None else response,
        )

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
        self.guard.reset()
        logger.info(f"User Request: {task}")

        context = self.short_memory.get_context()
        decision = self.decision_engine.decide(task)
        logger.info(f"Decision: {decision}")

        print(f"Task: {task}")
        print(f"Decision: {decision}")

        # ------------------------------------------------------------
        # MEMORY STORE - user shares personal information
        # ------------------------------------------------------------
        if decision == "memory_store":
            return self._handle_memory_store(task)

        # ------------------------------------------------------------
        # MEMORY RECALL - user asks what we remember
        # ------------------------------------------------------------
        if decision == "memory_recall":
            return self._handle_memory_recall(task)

        # ------------------------------------------------------------
        # GENERAL CHAT - normal conversation (no code, no tools)
        # ------------------------------------------------------------
        if decision == "chat":
            return self._handle_chat(task, context)

        # ------------------------------------------------------------
        # COLLABORATIVE WORKFLOW
        # ------------------------------------------------------------
        if decision == "workflow":
            return self._handle_workflow(task, context, progress_callback)

        # ------------------------------------------------------------
        # GITHUB TOOL (routes through the MCP layer)
        # ------------------------------------------------------------
        if decision == "github":
            return self._handle_github(task)

        # ------------------------------------------------------------
        # PROJECT ANALYSIS
        # ------------------------------------------------------------
        if decision == "project":
            logger.info("Routing -> Project Analyzer")
            response = self.project_analyzer.analyze_project(".")
            return self._finish(task, response, "Project Analyzer")

        # ------------------------------------------------------------
        # CODE ANALYSIS AGENT - analyze/review/quality-check existing code
        # ------------------------------------------------------------
        if decision == "code_analysis":
            logger.info("Routing -> Code Analysis Agent")
            return self._handle_code_analysis(task, context)

        # ------------------------------------------------------------
        # DEBUGGING AGENT
        # ------------------------------------------------------------
        if decision == "debug":
            logger.info("Routing -> Debugging Agent")
            response = self.debugging.debug_code(task)
            return self._finish(task, response, "Debugging Agent")

        # ------------------------------------------------------------
        # DOCUMENTATION AGENT
        # ------------------------------------------------------------
        if decision == "documentation":
            logger.info("Routing -> Documentation Agent")
            response = self.docs.explain(task)
            return self._finish(task, response, "Documentation Agent")

        # ------------------------------------------------------------
        # PLANNER AGENT
        # ------------------------------------------------------------
        if decision == "planner":
            logger.info("Routing -> Planner Agent")
            response = self.planner.execute(task, context)
            return self._finish(task, response, "Planner Agent")

        # ------------------------------------------------------------
        # PATCH TOOL - only for explicit code modification requests
        # ------------------------------------------------------------
        if decision == "patch":
            return self._handle_patch(task)

        # ------------------------------------------------------------
        # FILE TOOL
        # ------------------------------------------------------------
        if decision == "file":
            return self._handle_file(task)

        # ------------------------------------------------------------
        # CODING AGENT (+ optional code execution)
        # ------------------------------------------------------------
        return self._handle_coding(task, context, decision)

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
        response = self.chat.answer(task, context)
        return self._finish(task, response, "Chat Assistant")

    # =====================================================================
    # Workflow handler
    # =====================================================================
    def _handle_workflow(self, task, context, progress_callback=None):
        logger.info("Entering Collaborative Workflow")
        self.guard.reset()

        workflow_result = self.workflow_manager.execute(
            task,
            context,
            progress_callback=progress_callback,
        )
        clean_code_text = self.clean_code_output(workflow_result["coding"])

        final_response = f"""
### 📋 Planning Result

{workflow_result["planner"]}

### 💻 Code

```python
{clean_code_text}
```

### 🔍 Review Result

{workflow_result["review"]}

### 🧪 Code Analysis Result

{workflow_result["code_analysis"]}

### 📄 Documentation Result

{workflow_result["documentation"]}
""".strip()

        return self._finish(
            task,
            final_response,
            "Collaborative Workflow",
            extra={
                "workflow": workflow_result,
                "code": clean_code_text,
            },
            memory_message=(
                f"Collaborative workflow completed for: {task[:200]}"
            ),
        )

    # =====================================================================
    # Code Analysis handler
    # =====================================================================
    def _handle_code_analysis(self, task, context):
        """
        Analyze EXISTING code - never generate or modify it.

        Code may come from:
        - an uploaded file (the UI appends "Uploaded File:")
        - a filename mentioned in the request (read from disk)
        - raw code pasted directly in the message
        """
        agent_name = "Code Analysis Agent"
        code = self._extract_code_for_analysis(task)

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

        response = self.code_analysis.analyze(code, context)
        return self._finish(task, response, agent_name)

    @staticmethod
    def _extract_code_for_analysis(task):
        """
        Best-effort extraction of code from a user request.
        Returns None when no code could be found.
        """
        # 1) Uploaded file content (the UI inlines it after a marker)
        for marker in ("[Attached file: ", "[Uploaded File: ", "Uploaded File:"):
            if marker in task:
                tail = task.split(marker, 1)[1]
                # Strip the filename line (e.g. "app.py\n") - keep the code.
                first_line, sep, rest = tail.partition("\n")
                if sep and rest.strip():
                    return rest.strip()
                return tail.strip()

        # 2) Markdown code fences
        fence = re.search(r"```(?:python)?\s*\n(.*?)```", task, re.DOTALL)
        if fence:
            return fence.group(1).strip()

        # 3) A filename mentioned in the request that exists on disk
        filename = CoordinatorAgent._extract_filename(task)
        if filename and FileTool.exists(filename):
            return FileTool.read_file(filename)

        # 4) Raw code pasted directly (starts with code-ish prefixes)
        stripped = task.strip()
        if stripped.startswith(("def ", "class ", "import ", "from ", "print(", "async def")):
            return stripped

        # 5) Inline code after a colon: "Analyze this code: print('x')"
        for sep in (":\n", ": "):
            if sep in task:
                tail = task.split(sep, 1)[1].strip()
                if tail.startswith(("def ", "class ", "import ", "from ", "print(", "async def")):
                    return tail

        return None

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

    # =====================================================================
    # Coding handler (also handles execution when requested)
    # =====================================================================
    def _handle_coding(self, task, context, decision):
        agent_name = "Coding Agent"
        is_execution = decision == "execution"

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

Previous Conversation:
{context}

User Request:
{task}
"""

        response = self.coding.solve_task(prompt)

        # Pure code request: return ONLY the code. No file saving, no
        # patches, no execution. Tools (File/Patch/Code Executor) stay
        # reserved for explicit execution/file requests.
        if not is_execution:
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

            response = (
                f"{response}\n\n"
                "============\n"
                "Execution Output\n"
                "============\n"
                f"{output}"
            )

        if extra_lines:
            response = f"{response}\n\n" + "\n".join(extra_lines)

        return self._finish(task, response, agent_name)
