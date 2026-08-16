"""Tests for the LangGraph orchestration layer (upgraded Task 1)."""
from agents.coordinator import CoordinatorAgent
from agents.decision_engine import DecisionEngine
from agents.graph import build_graph, build_workflow_graph
from memory.memory import Memory
from memory.short_term_memory import ShortTermMemory


class FakeLLM:
    def __init__(self):
        self.calls = []

    @staticmethod
    def _to_text(prompt):
        if isinstance(prompt, list):
            return "\n".join(
                m.get("content", "") if isinstance(m, dict) else str(m)
                for m in prompt
            )
        return prompt

    @staticmethod
    def _user_request(prompt):
        """Extract the real request from the classifier prompt, ignoring
        the category examples listed above it."""
        text = FakeLLM._to_text(prompt)
        low = text.lower()
        if "user request:" in low and "category:" in low:
            tail = text.split("User request:", 1)[1]
            return tail.split("Category:", 1)[0].strip().lower()
        return low

    def ask(self, prompt):
        self.calls.append(prompt)
        low = self._to_text(prompt).lower()
        if low.lstrip().startswith("you are an intent classifier"):
            task = self._user_request(prompt)
            if "build a calculator" in task or "develop software that manages books" in task:
                return "workflow"
            if "my name is" in task:
                return "memory_store"
            if "what is my name" in task:
                return "memory_recall"
            if "debug" in task:
                return "debug"
            if "document" in task:
                return "documentation"
            if "plan" in task:
                return "planner"
            if "review" in task:
                return "review"
            if "analyze" in task:
                return "code_analysis"
            if (
                "write" in task or "function" in task or "code" in task
                or "optimize" in task
            ):
                return "coding"
            return "chat"
        if "extract it as a single line" in low:
            return "name = Muskan"
        if "return only the complete code" in low:
            return 'def add(a, b):\n    return a + b\n\ndef main():\n    print(add(2, 3))'
        if "you are an ai coding assistant" in low:
            return 'def reverse_string(s):\n    return s[::-1]'
        return 'print("hello")'


class FakeGuard:
    def can_call(self):
        return True

    def register_call(self):
        pass

    def reset(self):
        pass


def make_coordinator(tmp_path):
    memory = Memory()
    stm = ShortTermMemory(file_path=str(tmp_path / "stm.json"))
    return CoordinatorAgent(FakeLLM(), FakeGuard(), memory, stm)


def test_graph_builds_and_invokes(tmp_path):
    coord = make_coordinator(tmp_path)
    graph = build_graph(coord)
    state = graph.invoke({"task": "What is AI?", "context": "", "progress": None})
    assert state["agent"] == "Chat Assistant"
    assert state["response"]


def test_graph_routes_to_memory_store(tmp_path):
    coord = make_coordinator(tmp_path)
    result = coord.handle_task("My name is Muskan")
    assert result["agent"] == "Memory Store"
    assert coord.short_memory.get_facts().get("name") == "Muskan"


def test_workflow_subgraph_runs_three_stages(tmp_path):
    coord = make_coordinator(tmp_path)
    sub = build_workflow_graph(coord)
    seen = []
    state = sub.invoke(
        {
            "task": "Build a calculator application",
            "context": "",
            "progress": lambda i, t, n: seen.append(n),
        }
    )
    assert set(seen) == {"Planner Agent", "Coding Agent", "Documentation Agent"}
    assert set(state) >= {"planner", "coding", "documentation"}
    assert state["planner"] and state["coding"] and state["documentation"]


def test_main_graph_workflow_path(tmp_path):
    coord = make_coordinator(tmp_path)
    result = coord.handle_task("Build a calculator application")
    assert result["agent"] == "Collaborative Workflow"
    assert set(result["workflow"]) == {"planner", "coding", "documentation"}
    assert "###" in result["response"]
    assert result["code"]


def test_graph_shared_state_between_agents(tmp_path):
    """The coding stage must see the planner's output (shared state)."""
    coord = make_coordinator(tmp_path)
    sub = build_workflow_graph(coord)
    calls = coord.coding.solve_task
    captured = []

    def spy(task):
        captured.append(task)
        return calls(task)

    coord.coding.solve_task = spy
    sub.invoke({"task": "Build a calculator application", "context": ""})
    assert captured, "coding stage must run"
    assert "Implementation Plan" in captured[0]


def test_chat_follow_up_context_flows(tmp_path):
    """A follow-up chat turn must see the previous conversation in its
    context - regression: the chat node used to call chat.answer directly
    (bypassing _finish), so chat turns were never stored in short-term
    memory and follow-ups saw an empty conversation."""
    coord = make_coordinator(tmp_path)
    captured = []
    orig = coord.chat.answer
    coord.chat.answer = (
        lambda task, context: (captured.append((task, context)) or "reply")
    )
    try:
        coord.handle_task("What is AI?")
        coord.handle_task("Give one example")
    finally:
        coord.chat.answer = orig

    assert len(captured) == 2
    assert "What is AI?" in captured[-1][1]
    assert "Give one example" in captured[-1][0]


def test_coding_followup_skips_rag_project_context(tmp_path):
    """Follow-ups on just-generated code must NOT be augmented with
    retrieved project files. Regression: "Optimize it" retrieved
    tools/code_metrics.py from the project index and the coding agent
    echoed that file instead of updating the user's function."""
    coord = make_coordinator(tmp_path)

    # Simulate the previous turn: assistant generated code.
    coord.short_memory.add("user", "Write a Python function to reverse a string")
    coord.short_memory.add(
        "assistant",
        "def reverse_string_in_place(s):\n    return s[::-1]",
    )

    assert coord._is_coding_followup("Optimize it and add error handling") is True

    rag_calls = []
    orig = coord._augment_with_rag

    def spy(task, context):
        rag_calls.append(task)
        return f"{context}\n\n## Relevant project context\n\n{task}"

    coord._augment_with_rag = spy
    try:
        coord._handle_coding(
            "Optimize it and add error handling", "## Recent conversation\n\n...", "coding"
        )
    finally:
        coord._augment_with_rag = orig

    assert rag_calls == [], "RAG must be skipped for a coding follow-up"


def test_fresh_coding_request_after_workflow_keeps_rag(tmp_path):
    """A genuinely NEW coding request right after a workflow must keep
    RAG. Regression guard: the workflow now stores its generated code in
    memory, so the follow-up heuristic must not treat a fresh request
    ("Write a fibonacci function") as a follow-up of that code."""
    coord = make_coordinator(tmp_path)
    coord.handle_task("Build a calculator application")

    # The workflow's generated code is in the last assistant message.
    assert "def add" in coord.short_memory.get_messages()[-1]["message"]
    # ...but a fresh, fully-specified coding request is NOT a follow-up.
    assert coord._is_coding_followup("Write a fast fibonacci function") is False
    # Terse relative follow-up still counts.
    assert coord._is_coding_followup("Optimize it") is True


def test_fresh_coding_request_still_uses_rag(tmp_path):
    """A brand-new coding request (no prior generated code) keeps RAG
    augmentation so project awareness is not lost."""
    coord = make_coordinator(tmp_path)
    assert coord._is_coding_followup("Write a fast fibonacci function") is False

    rag_calls = []
    orig = coord._augment_with_rag

    def spy(task, context):
        rag_calls.append(task)
        return f"{context}\n\n## Relevant project context\n\n{task}"

    coord._augment_with_rag = spy
    try:
        coord._handle_coding(
            "Write a fast fibonacci function", "", "coding"
        )
    finally:
        coord._augment_with_rag = orig

    assert len(rag_calls) == 1
    assert rag_calls[0] == "Write a fast fibonacci function"


def test_debug_follow_up_context_flows(tmp_path):
    """A debug follow-up must see the previous conversation in its
    context - regression: the debug node used to call debug_code(task)
    without context, so "why does it crash now" lost all prior turns."""
    coord = make_coordinator(tmp_path)
    captured = []
    orig = coord.debugging.debug_code
    coord.debugging.debug_code = (
        lambda task, context="": (captured.append((task, context)) or "fixed")
    )
    try:
        coord.handle_task("What is AI?")
        coord.handle_task("The code crashes, debug it")
    finally:
        coord.debugging.debug_code = orig

    assert len(captured) == 1
    assert "The code crashes" in captured[-1][0]
    assert "What is AI?" in captured[-1][1], "debug must receive prior context"


def test_documentation_follow_up_context_flows(tmp_path):
    """A documentation follow-up must see the previous conversation."""
    coord = make_coordinator(tmp_path)
    captured = []
    orig = coord.docs.explain
    coord.docs.explain = (
        lambda task, context="": (captured.append((task, context)) or "docs")
    )
    try:
        coord.handle_task("Write a Python function to find factorial")
        coord.handle_task("Now document that function")
    finally:
        coord.docs.explain = orig

    assert len(captured) == 1
    assert "Now document" in captured[-1][0]
    assert "find factorial" in captured[-1][1], "docs must receive prior context"


def test_planner_follow_up_context_flows(tmp_path):
    """A planner follow-up must see the previous conversation."""
    coord = make_coordinator(tmp_path)
    captured = []
    orig = coord.planner.execute
    coord.planner.execute = (
        lambda task, context="": (captured.append((task, context)) or "plan")
    )
    try:
        coord.handle_task("Build a calculator application")
        coord.handle_task("Now plan the testing phase for that app")
    finally:
        coord.planner.execute = orig

    # The workflow stage itself calls planner.execute once, so expect the
    # follow-up to be the LAST call - and it must carry prior context.
    assert len(captured) == 2
    assert "testing phase" in captured[-1][0]
    assert "calculator" in captured[-1][1], "planner must receive prior context"


def test_code_analysis_follow_up_finds_code_in_context(tmp_path):
    """A code-analysis follow-up ("analyze this function") must find the
    just-generated code in the previous conversation. Regression: the
    extractor only scanned the task string, so follow-ups replied "no
    code found" even though the code was in context."""
    coord = make_coordinator(tmp_path)
    captured = []
    orig = coord.code_analysis.analyze
    coord.code_analysis.analyze = (
        lambda code, context="", include_metrics=False: (
            captured.append((code, context)) or "analysis"
        )
    )
    try:
        # Turn 1: assistant generates a palindrome function.
        coord.short_memory.add("user", "Write a Python function to check palindrome")
        coord.short_memory.add(
            "assistant",
            "def is_palindrome(s):\n    s = ''.join(c for c in s if c.isalnum()).lower()\n    return s == s[::-1]",
        )
        coord.handle_task("Analyze this function for code quality")
    finally:
        coord.code_analysis.analyze = orig

    assert len(captured) == 1
    code, _ = captured[0]
    assert "def is_palindrome" in code, "follow-up code must be extracted from context"


def test_workflow_follow_up_review_finds_generated_code(tmp_path):
    """After a Build Application, "review it" / "analyze it" must find
    the generated code. Regression: the workflow stored only a one-line
    summary in short-term memory, so the code-analysis follow-up replied
    "no code found" even though the app had just been generated."""
    coord = make_coordinator(tmp_path)
    captured = []
    orig = coord.reviewer.review
    coord.reviewer.review = lambda code: (captured.append(code) or "review")
    try:
        result = coord.handle_task("Build a calculator application")
        assert result["agent"] == "Collaborative Workflow"
        assert "def add" in result.get("code", "")
        # The generated code must be in the short-term memory entry.
        msgs = coord.short_memory.get_messages()
        assert "def add" in msgs[-1]["message"], (
            "workflow must store generated code in memory"
        )
        # Follow-up: review the generated code.
        follow = coord.handle_task("Review the code")
        assert follow["agent"] == "Reviewer Agent"
    finally:
        coord.reviewer.review = orig

    assert len(captured) == 1
    assert "def add" in captured[0], (
        "follow-up review must extract the workflow code"
    )


def test_code_follow_up_analyze_finds_code_in_context(tmp_path):
    """Code -> "analyze the above code" must extract the just-generated
    function from the conversation context."""
    coord = make_coordinator(tmp_path)
    captured = []
    orig = coord.code_analysis.analyze
    coord.code_analysis.analyze = (
        lambda code, context="", include_metrics=False: (
            captured.append(code) or "analysis"
        )
    )
    try:
        r = coord.handle_task("Write a Python function to reverse a string")
        assert r["agent"] == "Coding Agent"
        assert "def " in r["response"]
        follow = coord.handle_task("Analyze the above code")
        assert follow["agent"] == "Code Analysis Agent"
        assert "couldn't find any code" not in follow["response"]
    finally:
        coord.code_analysis.analyze = orig

    assert len(captured) == 1
    assert "def " in captured[0]


# ======================================================================
# Milestone 4 - intent-driven chain orchestration
# ======================================================================


def test_detect_chain_unit():
    """Chain detection only triggers on explicit compound requests."""
    de = DecisionEngine(model=None, guard=None, use_llm=False)
    assert de.detect_chain("Review this project") == "review_project"
    assert de.detect_chain("Review the codebase") == "review_project"
    assert de.detect_chain("Review the project architecture") == "review_project"
    assert de.detect_chain("Debug this code and document the fix") == "debug_document"
    assert de.detect_chain("Fix this bug and document it") == "debug_document"
    assert (
        de.detect_chain("Explain this code and generate documentation")
        == "explain_document"
    )
    assert de.detect_chain("Analyze this code and document it") == "explain_document"

    # Single-intent requests must NOT trigger chains (backward compat).
    assert de.detect_chain("Review the code") is None
    assert de.detect_chain("Review this app code") is None
    assert de.detect_chain("Debug this code") is None
    assert de.detect_chain("Fix this bug") is None
    assert de.detect_chain("Explain this code") is None
    assert de.detect_chain("Document this code") is None


def test_detect_chain_code_review_docs():
    """Compound coding-first requests trigger the coding -> analysis ->
    review -> documentation chain; single intents and non-coding compound
    requests keep their existing routing."""
    de = DecisionEngine(model=None, guard=None, use_llm=False)
    assert de.detect_chain(
        "Write Python code for a REST API endpoint, find possible bugs, "
        "review the code quality, and generate documentation."
    ) == "code_review_docs"
    assert de.detect_chain("Write code and review it") == "code_review_docs"
    assert de.detect_chain(
        "Create a Python file containing Binary Search, review it, fix "
        "any issues, and provide the final corrected version."
    ) == "code_review_docs"

    # Non-compound / non-coding-first requests stay unchanged.
    assert de.detect_chain("Write a Python function to sort a list") is None
    assert (
        de.detect_chain("Explain this code and generate documentation")
        == "explain_document"
    )
    assert de.detect_chain("Review this project") == "review_project"


def test_code_review_docs_chain_runs_four_agents(tmp_path):
    """Write Code -> Code Analysis -> Reviewer -> Documentation with the
    generated code shared through state."""
    coord = make_coordinator(tmp_path)
    seen = []
    result = coord.handle_task(
        "Write Python code for a REST API endpoint, find possible bugs, "
        "review the code quality, and generate documentation.",
        progress_callback=lambda i, t, n: seen.append(n),
    )
    assert result["agent"] == "Code Review & Docs Workflow"
    assert set(seen) == {
        "Coding Agent", "Code Analysis Agent", "Reviewer Agent",
        "Documentation Agent",
    }
    assert "Generated Code" in result["response"]
    assert "Reviewer Findings" in result["response"]
    assert {"code", "code_analysis", "review", "documentation"} <= set(
        result["workflow"]
    )


def test_code_review_docs_stages_share_generated_code(tmp_path):
    """The analysis, review and documentation stages must all receive
    the SAME generated code (shared state), not the raw request."""
    coord = make_coordinator(tmp_path)
    seen_code = []
    orig_analysis = coord.code_analysis.analyze
    orig_review = coord.reviewer.review

    def spy_analysis(code, context=""):
        seen_code.append(("analysis", code))
        return "analysis"

    def spy_review(code):
        seen_code.append(("review", code))
        return "review"

    coord.code_analysis.analyze = spy_analysis
    coord.reviewer.review = spy_review
    try:
        coord.handle_task(
            "Write Python code for a REST API endpoint, find possible "
            "bugs, review the code quality, and generate documentation."
        )
    finally:
        coord.code_analysis.analyze = orig_analysis
        coord.reviewer.review = orig_review

    assert len(seen_code) == 2
    code_from_analysis = seen_code[0][1]
    assert code_from_analysis == seen_code[1][1], (
        "analysis and review must act on the same generated code"
    )
    assert "def " in code_from_analysis


def _attached_marker(root, request="Review this project"):
    return (
        f"{request}\n\n"
        f"[Attached project: Project.zip] (extracted to: {root})\n"
        "Project files:\n- app.py"
    )


def _project_dir(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "app.py").write_text("print('hi')\n", encoding="utf-8")
    return root


def test_review_project_chain_runs_two_agents(tmp_path):
    """Review Project -> Project Analyzer -> Reviewer (shared state),
    on an uploaded project."""
    coord = make_coordinator(tmp_path)
    seen = []
    result = coord.handle_task(
        _attached_marker(_project_dir(tmp_path)),
        progress_callback=lambda i, t, n: seen.append(n),
    )
    assert result["agent"] == "Project Review Workflow"
    assert set(seen) == {"Project Analyzer", "Reviewer Agent"}
    assert "Reviewer Findings" in result["response"]
    assert "review" in result["workflow"]


def test_review_chain_reviewer_receives_analyzer_report(tmp_path):
    """The reviewer must receive the analyzer's report (shared state)."""
    coord = make_coordinator(tmp_path)
    captured = []
    orig = coord.reviewer.review

    def spy(report):
        captured.append(report)
        return "review done"

    coord.reviewer.review = spy
    try:
        coord.handle_task(_attached_marker(_project_dir(tmp_path)))
    finally:
        coord.reviewer.review = orig

    assert len(captured) == 1
    assert "Health Score" in captured[0] or "file_count" in captured[0].lower() or captured[0]


def test_review_generated_project_uses_reviewer_not_workspace_scan(tmp_path):
    """Regression: "Review the project" after BUILDING an app (generated
    code, no uploaded ZIP) must review the generated code via the
    Reviewer Agent - never scan the app's own workspace."""
    coord = make_coordinator(tmp_path)
    coord._active["code"] = "def hospital():\n    return 'ok'\n"
    coord._active["workflow"] = "Hospital Management System"
    coord._active["project_root"] = None
    captured = []
    orig = coord.reviewer.review
    coord.reviewer.review = lambda code: (captured.append(code) or "review done")
    try:
        result = coord.handle_task(
            "Review the project and identify one important issue."
        )
    finally:
        coord.reviewer.review = orig
    assert result["agent"] == "Reviewer Agent"
    assert captured and "def hospital" in captured[0]


def test_review_project_chain_still_runs_for_uploaded_project(tmp_path):
    """An uploaded ZIP project (project_root set) keeps the project-review
    chain - the downgrade only applies to generated code without a root."""
    import os
    import tempfile

    root = tempfile.mkdtemp()
    with open(os.path.join(root, "app.py"), "w", encoding="utf-8") as f:
        f.write("def health():\n    return 'ok'\n")
    coord = make_coordinator(tmp_path)
    coord._active["project_root"] = root
    coord._active["workflow"] = "Uploaded Project"
    result = coord.handle_task("Review this project")
    assert result["agent"] == "Project Review Workflow"


def test_debug_document_chain_runs_two_agents(tmp_path):
    """Debug Code -> Debugger -> Documentation."""
    coord = make_coordinator(tmp_path)
    result = coord.handle_task("Debug this code and document the fix")
    assert result["agent"] == "Debug & Document Workflow"
    assert "Documentation" in result["response"]
    assert {"debug", "documentation"} <= set(result["workflow"])


def test_debug_chain_docs_receives_debug_output(tmp_path):
    """The documentation stage must see the debugger's output."""
    coord = make_coordinator(tmp_path)
    captured = []
    orig = coord.docs.explain

    def spy(task, context=""):
        captured.append(task)
        return "docs"

    coord.docs.explain = spy
    try:
        coord.handle_task("Debug this code and document the fix")
    finally:
        coord.docs.explain = orig

    assert len(captured) == 1
    assert "Debugging session" in captured[0]


def test_explain_document_chain_runs_two_agents(tmp_path):
    """Explain Code -> Code Analysis -> Documentation."""
    coord = make_coordinator(tmp_path)
    result = coord.handle_task("Explain this code and generate documentation")
    assert result["agent"] == "Explain & Document Workflow"
    assert "Documentation" in result["response"]
    assert {"code_analysis", "documentation"} <= set(result["workflow"])


def test_chain_output_stored_in_memory_for_followups(tmp_path):
    """Chain results must land in short-term memory so terse follow-ups
    ("summarize the review") work without re-running the chain."""
    coord = make_coordinator(tmp_path)
    coord.handle_task(_attached_marker(_project_dir(tmp_path)))
    msgs = coord.short_memory.get_messages()
    assert msgs[-1]["role"] == "assistant"
    assert "Health Score" in msgs[-1]["message"]


def test_plain_single_intents_stay_single_agent(tmp_path):
    """Backward compatibility: single-intent requests keep one agent."""
    coord = make_coordinator(tmp_path)
    assert coord.handle_task("Debug this error")["agent"] == "Debugging Agent"
    assert coord.handle_task("Review this code")["agent"] == "Reviewer Agent"
    assert coord.handle_task("Document this code")["agent"] == "Documentation Agent"


def test_code_analysis_fresh_request_without_code_still_asks(tmp_path):
    """A brand-new analysis request with no code anywhere (no task code,
    no prior generated code) keeps the friendly "couldn't find code"
    response instead of crashing."""
    coord = make_coordinator(tmp_path)
    coord.short_memory.add("user", "What is AI?")
    coord.short_memory.add(
        "assistant", "AI is the simulation of human intelligence by machines."
    )
    result = coord.handle_task("Analyze this code for quality issues")
    assert result["agent"] == "Code Analysis Agent"
    assert "couldn't find any code" in result["response"]


# ======================================================================
# Section 3 - "Review the project and fix it" runs a 3-agent pipeline,
# and uploaded projects are used on the very first turn
# ======================================================================

def test_detect_chain_review_and_fix():
    """\"Review this project and fix ...\" (and \"Review and fix this
    project\") trigger the review+fix chain; plain reviews and
    single-intent requests keep their old routing."""
    de = DecisionEngine(model=None, guard=None, use_llm=False)
    assert (
        de.detect_chain("Review this project and fix the most important bug")
        == "review_project_fix"
    )
    assert (
        de.detect_chain("Review the codebase and fix any issues")
        == "review_project_fix"
    )
    # Fix verb before the project noun must also trigger the chain.
    assert de.detect_chain("Review and fix this project") == "review_project_fix"
    # Plain requests are untouched.
    assert de.detect_chain("Review this project") == "review_project"
    assert de.detect_chain("Review the code") is None
    assert de.detect_chain("Fix this bug") is None
    # Code-only compound requests do NOT become a project review.
    assert de.detect_chain("Review this code and fix it") is None


def test_review_project_fix_chain_runs_three_agents(tmp_path):
    """Review + fix -> Project Analyzer -> Reviewer -> Coding, and the
    corrected code lands in the workflow output (uploaded project)."""
    coord = make_coordinator(tmp_path)
    seen = []
    result = coord.handle_task(
        _attached_marker(
            _project_dir(tmp_path), "Review this project and fix the most important bug"
        ),
        progress_callback=lambda i, t, n: seen.append(n),
    )
    assert result["agent"] == "Project Review & Fix Workflow"
    assert set(seen) == {"Project Analyzer", "Reviewer Agent", "Coding Agent"}
    assert "Corrected Code" in result["response"]
    assert result["workflow"].get("code"), "chain must produce corrected code"


def test_review_and_fix_this_project_chain_runs_three_agents(tmp_path):
    """\"Review and fix this project\" (fix verb before the noun) runs
    the same Analyzer -> Reviewer -> Coding pipeline and returns code."""
    coord = make_coordinator(tmp_path)
    seen = []
    result = coord.handle_task(
        _attached_marker(_project_dir(tmp_path), "Review and fix this project"),
        progress_callback=lambda i, t, n: seen.append(n),
    )
    assert result["agent"] == "Project Review & Fix Workflow"
    assert set(seen) == {"Project Analyzer", "Reviewer Agent", "Coding Agent"}
    assert "Corrected Code" in result["response"]
    assert result["workflow"].get("code")


def test_review_project_first_turn_uses_attached_marker_root(tmp_path):
    """Regression: the very first request after a ZIP upload must analyze
    the uploaded project - never the app's own workspace. The active
    context is only populated AFTER the graph completes, so the chain
    must read the root from the current message's marker."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "app.py").write_text("print('hi')\n", encoding="utf-8")
    coord = make_coordinator(tmp_path)
    captured = {}
    orig = coord.project_analyzer.analyze_project
    coord.project_analyzer.analyze_project = lambda r: (
        captured.setdefault("root", r) or "project report"
    )
    try:
        task = (
            "Review this project\n\n"
            f"[Attached project: Project.zip] (extracted to: {root})\n"
            "Project files:\n- app.py"
        )
        result = coord.handle_task(task)
        assert result["agent"] == "Project Review Workflow"
    finally:
        coord.project_analyzer.analyze_project = orig
    assert str(captured.get("root")) == str(root), (
        "must analyze the uploaded project, not the workspace"
    )


def _attached_project_task(request_text, root):
    return (
        f"{request_text}\n\n"
        f"[Attached project: Project.zip] (extracted to: {root})\n"
        "Project files:\n- app.py"
    )


def test_project_sources_injected_into_debug_on_first_turn(tmp_path):
    """\"Fix the bug in this project\" right after a ZIP upload must hand
    the debugging agent the ACTUAL project sources so it can return
    corrected code instead of a generic answer."""
    root = tmp_path / "proj3"
    root.mkdir()
    (root / "app.py").write_text(
        "def divide(a, b):\n    return a / b\n", encoding="utf-8"
    )
    coord = make_coordinator(tmp_path)
    captured = []
    orig = coord.debugging.debug_code
    coord.debugging.debug_code = (
        lambda task, context="": (captured.append(task) or "fixed")
    )
    try:
        task = _attached_project_task("Fix the bug in this project", root)
        result = coord.handle_task(task)
        assert result["agent"] == "Debugging Agent"
    finally:
        coord.debugging.debug_code = orig
    assert captured
    assert "[Uploaded project sources]" in captured[0]
    assert "def divide" in captured[0], "project source code must reach the debugger"


def test_find_bugs_in_project_routes_to_debug_with_sources(tmp_path):
    """\"Find bugs in this project\" must route to the Debugging Agent
    (not Project Analysis or Documentation) and carry the real sources."""
    root = tmp_path / "proj4"
    root.mkdir()
    (root / "app.py").write_text(
        "def divide(a, b):\n    return a / b\n", encoding="utf-8"
    )
    coord = make_coordinator(tmp_path)
    captured = []
    orig = coord.debugging.debug_code
    coord.debugging.debug_code = (
        lambda task, context="": (captured.append(task) or "fixed")
    )
    try:
        task = _attached_project_task("Find bugs in this project", root)
        result = coord.handle_task(task)
        assert result["agent"] == "Debugging Agent"
    finally:
        coord.debugging.debug_code = orig
    assert captured
    assert "[Uploaded project sources]" in captured[0]
    assert "def divide" in captured[0]
