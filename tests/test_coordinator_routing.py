from agents.coordinator import CoordinatorAgent
from memory.memory import Memory
from memory.short_term_memory import ShortTermMemory


class FakeLLM:
    def __init__(self):
        self.calls = []

    @staticmethod
    def _to_text(prompt):
        """LangChain format_messages() returns a list of message dicts;
        normalize to plain text for classification."""
        if isinstance(prompt, list):
            return "\n".join(
                m.get("content", "")
                if isinstance(m, dict)
                else str(m)
                for m in prompt
            )
        return prompt

    @staticmethod
    def _user_request(prompt):
        """Extract the real user request from the classifier prompt,
        ignoring the category examples listed above it."""
        text = FakeLLM._to_text(prompt)
        low = text.lower()
        if "user request:" in low and "category:" in low:
            tail = text.split("User request:", 1)[1]
            return tail.split("Category:", 1)[0].strip().lower()
        return low

    def ask(self, prompt):
        self.calls.append(prompt)
        low = FakeLLM._to_text(prompt).lower()

        # Intent classifier prompt. Match on the PROMPT'S FIRST LINE, not
        # just the phrase anywhere: RAG can inject project files into
        # other prompts (e.g. the chat prompt retrieves a chunk of
        # decision_engine.py containing "intent classifier"), and those
        # must not be treated as classifier calls.
        if low.lstrip().startswith("you are an intent classifier"):
            task = self._user_request(prompt)
            if "my name is" in task:
                return "memory_store"
            if "what is my name" in task:
                return "memory_recall"
            if "develop software that manages books" in task:
                return "workflow"
            if "build a calculator" in task:
                return "workflow"
            if "what is ai" in task:
                return "chat"
            if "write a python function to find factorial" in task:
                return "coding"
            if "analyze this code" in task or "code quality" in task:
                return "code_analysis"
            if "run" in task or "execute" in task:
                return "execution"
            if "file" in task and any(
                kw in task for kw in ["create", "read", "delete", "write", "update"]
            ):
                return "file"
            return "chat"

        # Fact extraction prompt
        if "extract it as a single line" in low:
            return "name = Muskan"

        # Test input generation
        if "test inputs" in low:
            return "5"

        # Coding agent task: returns two FILE:-wrapped code blocks
        # (matches the coordinator's coding prompt "You are an AI coding
        # assistant.") so multi-file responses are exercised too.
        # Checked BEFORE the code-analysis marker: RAG context appended to
        # the coding prompt can legitimately mention "code analysis agent"
        # (e.g. retrieved prompts/code_analysis_prompt.py), so the coding
        # marker must win.
        if "you are an ai coding assistant" in low:
            return (
                'FILE: generated_program.py\nprint("hello")' +
                '\n\nFILE: helper.py\nprint("world")'
            )

        # Code analysis agent prompt
        if "code analysis agent" in low:
            return "### Code Quality Report\nScore: 88/100"

        # Coding / general fallback
        return 'print("hello")'


class FakeGuard:
    def __init__(self):
        self.count = 0

    def can_call(self):
        return True

    def register_call(self):
        self.count += 1

    def reset(self):
        self.count = 0


def make_coordinator(tmp_path):
    memory = Memory()
    short_memory = ShortTermMemory(
        file_path=str(tmp_path / "stm.json")
    )
    return CoordinatorAgent(FakeLLM(), FakeGuard(), memory, short_memory)


class UnknownIntentLLM(FakeLLM):
    """Classifier always returns an invalid category, forcing the keyword
    fallback - used to test deterministic fallback routing."""

    def ask(self, prompt):
        low = FakeLLM._to_text(prompt).lower()
        if low.lstrip().startswith("you are an intent classifier"):
            return "unknown"
        return super().ask(prompt)


def make_fallback_coordinator(tmp_path):
    memory = Memory()
    short_memory = ShortTermMemory(
        file_path=str(tmp_path / "stm.json")
    )
    return CoordinatorAgent(UnknownIntentLLM(), FakeGuard(), memory, short_memory)


def test_memory_store_routing(tmp_path):
    coord = make_coordinator(tmp_path)
    result = coord.handle_task("My name is Muskan")

    assert result["agent"] == "Memory Store"
    assert "stored" in result["response"].lower()
    assert coord.short_memory.get_facts().get("name") == "Muskan"


def test_memory_recall_routing(tmp_path):
    coord = make_coordinator(tmp_path)
    coord.handle_task("My name is Muskan")

    result = coord.handle_task("What is my name?")

    assert result["agent"] == "Memory Recall"
    assert "Muskan" in result["response"]
    assert "name" in result["response"].lower()


def test_chat_routing(tmp_path):
    coord = make_coordinator(tmp_path)
    result = coord.handle_task("What is AI?")

    assert result["agent"] == "Chat Assistant"
    assert result["response"] == 'print("hello")'


def test_workflow_routing(tmp_path):
    coord = make_coordinator(tmp_path)
    result = coord.handle_task("Build a calculator application")

    assert result["agent"] == "Collaborative Workflow"
    assert "workflow" in result
    assert "code" in result
    # Upgraded pipeline: Planner -> Coding -> Documentation only
    assert set(result["workflow"]) == {"planner", "coding", "documentation"}


def test_coding_routing(tmp_path):
    coord = make_coordinator(tmp_path)
    result = coord.handle_task("Write a Python function to find factorial")

    assert result["agent"] == "Coding Agent"
    assert "print" in result["response"]
    # Pure code request: only code, no FILE: header, no "Saved:" line
    assert "FILE:" not in result["response"]
    assert "Saved:" not in result["response"]


def test_code_analysis_routing(tmp_path):
    coord = make_coordinator(tmp_path)
    result = coord.handle_task(
        "Analyze this code\n```python\ndef add(a, b):\n    return a + b\n```"
    )

    assert result["agent"] == "Code Analysis Agent"
    assert "Code Quality" in result["response"]


def test_coding_does_not_write_files_for_pure_code(tmp_path, monkeypatch):
    writes = []
    monkeypatch.setattr(
        "agents.coordinator.FileTool.write_multiple_files",
        lambda files: writes.append(files) or ["Saved: generated_program.py"],
    )
    coord = make_coordinator(tmp_path)
    result = coord.handle_task("Write a Python function to find factorial")

    assert result["agent"] == "Coding Agent"
    assert writes == []  # pure code request must NOT touch the file system


def test_file_create_saves_actual_content_not_read_code(tmp_path, monkeypatch):
    """Creating a file stores the actual code, NOT a wrapper script."""
    monkeypatch.chdir(tmp_path)
    coord = make_coordinator(tmp_path)
    result = coord.handle_task(
        "Create a file called demo.py with this code: print('hello')"
    )

    assert result["agent"] == "File Tool"
    with open("demo.py", encoding="utf-8") as f:
        content = f.read()
    assert 'print("hello")' in content
    assert "file.write(" not in content
    assert "file.open" not in content


def test_file_create_unwraps_wrapper_script(tmp_path, monkeypatch):
    """Wrapper scripts (open/write/close) are unwrapped to inner content."""
    monkeypatch.chdir(tmp_path)
    coord = make_coordinator(tmp_path)

    def wrapper_response(prompt):
        return (
            'file = open("demo.py", "w")' +
            '\nfile.write(\'print("hello")\')' +
            '\nfile.close()'
        )

    coord.coding.solve_task = wrapper_response

    result = coord.handle_task(
        "Create a file called demo.py with this code: print('hello')"
    )

    assert result["agent"] == "File Tool"
    with open("demo.py", encoding="utf-8") as f:
        content = f.read()
    assert 'print("hello")' in content
    assert "file.write(" not in content


def test_file_update_unwraps_wrapper_script(tmp_path, monkeypatch):
    """UPDATE requests returning wrapper scripts are unwrapped too."""
    monkeypatch.chdir(tmp_path)
    with open("demo.py", "w", encoding="utf-8") as f:
        f.write('print("old")')

    coord = make_coordinator(tmp_path)

    def wrapper_response(prompt):
        return (
            'file = open("demo.py", "w")' +
            '\nfile.write(\'print("new version")\')' +
            '\nfile.close()'
        )

    coord.coding.solve_task = wrapper_response

    result = coord.handle_task("Update the file demo.py to print new version")

    assert result["agent"] == "File Tool"
    assert "updated" in result["response"].lower()
    with open("demo.py", encoding="utf-8") as f:
        content = f.read()
    assert 'print("new version")' in content
    assert "file.write(" not in content


def test_file_create_unwraps_escaped_quotes(tmp_path, monkeypatch):
    """file.write(\"print(\\\"hello\\\")\") is decoded without backslashes."""
    monkeypatch.chdir(tmp_path)
    coord = make_coordinator(tmp_path)

    def wrapper_response(prompt):
        return (
            'file = open("demo.py", "w")' +
            '\nfile.write("print(\\"hello\\")")' +
            '\nfile.close()'
        )

    coord.coding.solve_task = wrapper_response

    result = coord.handle_task(
        "Create a file called demo.py with this code: print('hello')"
    )

    assert result["agent"] == "File Tool"
    with open("demo.py", encoding="utf-8") as f:
        content = f.read()
    assert 'print("hello")' in content
    assert '\\"' not in content


def test_file_read_returns_file_content(tmp_path, monkeypatch):
    """Reading a file returns the stored content, not code."""
    monkeypatch.chdir(tmp_path)
    with open("data.txt", "w", encoding="utf-8") as f:
        f.write("actual file content here")

    coord = make_coordinator(tmp_path)
    result = coord.handle_task("Read the file data.txt")

    assert result["agent"] == "File Tool"
    assert "actual file content here" in result["response"]


def test_execution_saves_file_and_runs_code(tmp_path, monkeypatch):
    writes = []
    monkeypatch.setattr(
        "agents.coordinator.FileTool.write_multiple_files",
        lambda files: writes.append(files) or ["Saved: generated_program.py"],
    )
    executed = []
    coord = make_coordinator(tmp_path)

    # Patch the coding agent's tool bridge so no real subprocess runs.
    coord.coding.use_tool = lambda task, tool_input: (
        executed.append(tool_input)
        or {"success": True, "result": "Hello World"}
    )

    result = coord.handle_task("Run this Python script")

    assert result["agent"] == "Code Executor"
    assert writes != []  # execution saves the generated file
    assert executed != []  # code executor was actually invoked
    assert "Hello World" in result["response"]


def test_followup_verb_routing_uses_active_context(tmp_path):
    """Milestone 5: terse follow-ups on generated code must route to the
    specialized agent that acts on that code - without re-pasting it."""
    coord = make_fallback_coordinator(tmp_path)
    coord._active["topic"] = "calculator"
    coord._active["code"] = (
        "def add(x, y):\n    return x + y\n\ndef divide(x, y):\n"
        "    if y == 0: raise ZeroDivisionError()\n    return x / y\n"
    )

    assert coord.handle_task("Review it")["agent"] == "Reviewer Agent"
    assert coord.handle_task("Analyze it")["agent"] == "Code Analysis Agent"
    assert coord.handle_task("Explain line by line")["agent"] == "Documentation Agent"
    assert coord.handle_task("Explain time complexity")["agent"] == "Code Analysis Agent"
    assert coord.handle_task("Find bugs")["agent"] == "Debugging Agent"
    assert coord.handle_task("Add comments")["agent"] == "Documentation Agent"
    assert coord.handle_task("Generate README")["agent"] == "Documentation Agent"
    assert coord.handle_task("Optimize it")["agent"] == "Coding Agent"
    assert coord.handle_task("Convert it into Java")["agent"] == "Coding Agent"
    assert coord.handle_task("Add a login module")["agent"] == "Coding Agent"


def test_active_context_block_injected_on_followup(tmp_path):
    """A terse follow-up must receive the active code in its prompt."""
    coord = make_fallback_coordinator(tmp_path)
    captured = []
    orig = coord.reviewer.review
    coord.reviewer.review = lambda code: (captured.append(code) or "review")
    try:
        coord._active["topic"] = "calculator"
        coord._active["code"] = "def add(x, y):\n    return x + y\n"
        result = coord.handle_task("Review it")
        assert result["agent"] == "Reviewer Agent"
    finally:
        coord.reviewer.review = orig

    assert len(captured) == 1
    assert "def add" in captured[0], "follow-up must carry the active code"


def test_classify_followup_detects_topic_change(tmp_path):
    """A new subject must start a new reasoning path; references and
    relative modifiers must continue the active topic."""
    coord = make_fallback_coordinator(tmp_path)
    coord.handle_task("What is AI?")

    assert coord._classify_followup("Explain Operating System") == "new_topic"
    assert coord._classify_followup("Explain Cloud Computing") == "new_topic"
    assert coord._classify_followup("Explain it in simple words") == "followup"
    assert coord._classify_followup("Give one example") == "followup"
    assert coord._classify_followup("Give disadvantages") == "followup"
    assert coord._classify_followup("Optimize it") == "followup"


def test_time_complexity_followup_routes_to_code_analysis(tmp_path):
    """'Explain the time complexity' after generated code refers back to
    that code (complexity is generic work vocabulary) and must reach the
    Code Analysis Agent - not documentation or generic chat."""
    coord = make_fallback_coordinator(tmp_path)
    coord._active["topic"] = "binary search"
    coord._active["code"] = (
        "def binary_search(arr, target):\n"
        "    low, high = 0, len(arr) - 1\n"
        "    while low <= high:\n        mid = (low + high) // 2\n"
        "        if arr[mid] == target:\n            return mid\n"
        "        elif arr[mid] < target:\n            low = mid + 1\n"
        "        else:\n            high = mid - 1\n"
        "    return -1\n"
    )

    assert coord._classify_followup("Explain the time complexity") == "followup"
    result = coord.handle_task("Explain the time complexity")
    assert result["agent"] == "Code Analysis Agent"


def test_followup_after_workflow_keeps_generated_code(tmp_path):
    """A follow-up right after a Build Application workflow must reuse the
    workflow's generated code automatically (no re-paste)."""
    coord = make_fallback_coordinator(tmp_path)
    captured = []
    orig = coord.reviewer.review
    coord.reviewer.review = lambda code: (captured.append(code) or "review")
    try:
        result = coord.handle_task("Build a calculator application")
        assert result["agent"] == "Collaborative Workflow"
        assert result.get("code"), "workflow must produce code"

        follow = coord.handle_task("Review the generated application")
        assert follow["agent"] == "Reviewer Agent"
    finally:
        coord.reviewer.review = orig

    assert len(captured) == 1
    assert result["code"].strip() in captured[0], (
        "workflow code must flow into follow-up"
    )


def test_extract_code_prefers_uploaded_project_over_stale_conversation(tmp_path):
    """'Analyze the project' right after a ZIP upload must analyze the
    uploaded project's sources - never older generated code from the
    conversation."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8"
    )
    (root / "utils.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    task = (
        "Analyze the project.\n\n"
        f"[Attached project: Project.zip] (extracted to: {root})\n"
        "Project files:\n- app.py\n- utils.py"
    )
    context = (
        "## Recent conversation\nAssistant: def binary_search(arr, target):\n"
        "    pass\n"
    )
    code = CoordinatorAgent._extract_code_for_analysis(task, context, {})
    assert code is not None
    assert "from flask import Flask" in code, "must use the project sources"
    assert "def add(a, b)" in code
    assert "binary_search" not in code, "stale conversation code must not win"


def test_extract_code_prefers_active_project_over_conversation(tmp_path):
    """A follow-up ('Review it') on an uploaded project must use the
    project sources even when the conversation carries older code."""
    root = tmp_path / "proj2"
    root.mkdir()
    (root / "app.py").write_text("print('project app')\n", encoding="utf-8")
    context = (
        "## Recent conversation\nAssistant: def stale_code():\n    pass\n"
    )
    code = CoordinatorAgent._extract_code_for_analysis(
        "Review it", context, {"project_root": str(root)}
    )
    assert code is not None
    assert "project app" in code
    assert "stale_code" not in code


def test_extract_code_stops_at_next_inlined_section():
    """Regression: when the UI inlines an attached file followed by the
    previously generated code, extraction must return ONLY the attached
    file's code - not bleed into the following context blocks."""
    task = (
        "Analyze the attached file\n\n"
        "[Attached file: hello.py]\n"
        "def greet(name):\n"
        "    return f'Hello, {name}'\n"
        "\n"
        "[Previously generated code]\n"
        "# operations.py\n"
        "def add(x, y):\n"
        "    return x + y\n"
    )
    code = CoordinatorAgent._extract_code_for_analysis(task)
    assert code is not None
    assert "def greet" in code
    assert "operations.py" not in code, "must not bleed into later sections"
    assert "def add" not in code, "must not bleed into later sections"

    # Same for a follow-up carrying previously generated code alone.
    follow = (
        "review the generated code\n\n"
        "[Previously generated code]\n"
        "# operations.py\n"
        "def add(x, y):\n"
        "    return x + y\n"
    )
    code2 = CoordinatorAgent._extract_code_for_analysis(follow)
    assert code2 is not None and "def add" in code2
    assert "[Previous assistant response]" not in (code2 or "")


def test_doc_generation_after_build_is_followup_and_upgrades(tmp_path):
    """Regression: "Generate REST API documentation." after a Build
    Application must be a follow-up (not a new topic that wipes the
    workflow code), so the next "Explain the architecture." still routes
    to the Documentation Agent with the app in context."""
    coord = make_fallback_coordinator(tmp_path)

    assert coord.handle_task("Build a Hospital Management System")["agent"] == (
        "Collaborative Workflow"
    )
    assert coord._classify_followup("Generate REST API documentation.") == "followup"
    assert coord.handle_task("Generate REST API documentation.")["agent"] == (
        "Documentation Agent"
    )
    assert coord.handle_task("Explain the architecture.")["agent"] == (
        "Documentation Agent"
    )


def test_single_word_new_subject_starts_fresh_topic(tmp_path):
    """Regression: a one-word subject can still be a brand-new topic
    ("Explain Kubernetes." after a chat about Cloud Computing) instead of
    blindly continuing the active topic."""
    coord = make_fallback_coordinator(tmp_path)
    coord.handle_task("Explain Cloud Computing.")

    assert coord._classify_followup("Explain Kubernetes.") == "new_topic"
    # Generic work vocabulary still continues the active context.
    assert coord._classify_followup("Explain the architecture.") == "followup"


def test_which_language_do_i_like_is_memory_recall(tmp_path):
    """Regression: "Which programming language do I like?" is a question
    about the user - the word "programming" must not defeat the
    memory-recall fast path."""
    coord = make_fallback_coordinator(tmp_path)
    coord.handle_task("My favorite language is Python.")

    result = coord.handle_task("Which programming language do I like?")
    assert result["agent"] == "Memory Recall"


def test_generate_readme_for_project_routes_to_documentation(tmp_path):
    """Regression: "Generate README for this project." is documentation
    work - the "project" keyword must not route it to the Project
    Analyzer. With an uploaded project attached, it reaches the
    Documentation Agent."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "app.py").write_text("print('hi')\n", encoding="utf-8")
    task = (
        "Generate README for this project.\n\n"
        f"[Attached project: Project.zip] (extracted to: {root})\n"
        "Project files:\n- app.py"
    )
    coord = make_fallback_coordinator(tmp_path)
    result = coord.handle_task(task)
    assert result["agent"] == "Documentation Agent"


def test_chat_followup_stays_in_chat(tmp_path):
    """Regression: an explain-style follow-up on a CONVERSATIONAL topic
    (no code in context) must stay in Chat - it must not be upgraded to
    the Documentation Agent and forced into a documentation template."""
    coord = make_fallback_coordinator(tmp_path)
    coord.handle_task("What is AI?")
    assert coord._classify_followup("Explain it with an example.") == "followup"

    result = coord.handle_task("Explain it with an example.")
    assert result["agent"] == "Chat Assistant"


def test_explain_followup_on_code_routes_to_documentation(tmp_path):
    """An explain follow-up on GENERATED CODE must reach the
    Documentation Agent ("Explain the above code", "Explain it in simple
    words" after code was written)."""
    coord = make_fallback_coordinator(tmp_path)
    coord._active["code"] = "def binary_search(arr, target):\n    pass\n"
    coord._active["topic"] = "binary search"

    assert coord.handle_task("Explain it in simple words")["agent"] == (
        "Documentation Agent"
    )


def test_followup_verbs_never_misroute_to_documentation(tmp_path):
    """Regression: "Optimize it" and "Find bugs" after generated code
    must reach Coding / Debugging - never Documentation, even when the
    LLM classifier would guess documentation for an explain-y verb."""
    coord = make_fallback_coordinator(tmp_path)
    coord._active["code"] = "def add(x, y):\n    return x + y\n"
    coord._active["topic"] = "calculator"

    assert coord.handle_task("Optimize it")["agent"] == "Coding Agent"
    assert coord.handle_task("Find bugs")["agent"] == "Debugging Agent"


def test_workflow_build_tracks_generated_project(tmp_path):
    """A Build Application workflow must store the generated project as
    the CURRENT PROJECT CONTEXT (files) so follow-ups never ask the user
    to re-provide it."""
    coord = make_fallback_coordinator(tmp_path)
    result = coord.handle_task("Build a Hospital Management System")
    assert result["agent"] == "Collaborative Workflow"

    assert coord._active["workflow"], "workflow label must be stored"
    assert coord._active["code"], "generated code must be stored"
    assert coord._active["project_files"], "project files must be tracked"
    assert any(".py" in f for f in coord._active["project_files"]), (
        "a python project file must be tracked"
    )


def test_workflow_followup_keeps_project_context(tmp_path):
    """After a Build, a follow-up must keep the project context so the
    next request operates on the SAME generated project."""
    coord = make_fallback_coordinator(tmp_path)
    coord.handle_task("Build a Hospital Management System")

    assert coord._classify_followup("Add Login Module") == "followup"
    assert coord._classify_followup("Review it") == "followup"
    assert coord._classify_followup("Generate REST API documentation") == "followup"
    block = coord._active_context_block("Add Login Module")
    assert block and "Hospital" in block or "workflow" in (block or "").lower()


def test_small_inline_code_in_chat_does_not_mark_code_context():
    """A chat answer that contains a SHORT inline code illustration must
    not mark the conversation as code context - otherwise explain
    follow-ups would wrongly upgrade to the Documentation Agent."""
    assert not CoordinatorAgent._looks_like_code(
        "AI is intelligence in machines. For example:\ndef greet():\n    print('hi')\nThat is simple."
    )
    # Non-Python code output (e.g. a model answering a "write Python"
    # request in Java) is still CODE and must keep the code context.
    assert CoordinatorAgent._looks_like_code(
        "public class BinarySearch {\n"
        "    public static int binarySearch(int[] arr, int target) {\n"
        "        int low = 0;\n"
        "        int high = arr.length - 1;\n"
        "        while (low <= high) {\n"
        "            int mid = (low + high) / 2;\n"
        "            if (arr[mid] == target) {\n"
        "                return mid;\n"
        "            } else if (arr[mid] < target) {\n"
        "                low = mid + 1;\n"
        "            } else {\n"
        "                high = mid - 1;\n"
        "            }\n"
        "        }\n"
        "        return -1;\n"
        "    }\n"
        "}\n"
    )
    assert CoordinatorAgent._looks_like_code(
        "def binary_search(arr, target):\n    low, high = 0, len(arr) - 1\n"
        "    while low <= high:\n        mid = (low + high) // 2\n"
        "        if arr[mid] == target:\n            return mid\n"
        "        elif arr[mid] < target:\n            low = mid + 1\n"
        "        else:\n            high = mid - 1\n    return -1\n"
    )


def test_conversational_explain_followup_stays_chat(tmp_path):
    """Regression: after a Chat turn (no code context), an explain
    follow-up must stay in Chat even when the LLM classifier guessed
    "documentation" for the explain verb."""
    coord = make_fallback_coordinator(tmp_path)
    coord.handle_task("What is AI?")

    # Simulate the LLM classifier guessing wrong on the follow-up.
    decision = coord.decision_engine.decide("Explain it with an example.")
    override = coord._override_followup_decision(
        "Explain it with an example.", "followup", "documentation"
    )
    assert override == "chat", "conversational explain must be downgraded to chat"

    result = coord.handle_task("Explain it with an example.")
    assert result["agent"] == "Chat Assistant"


def test_code_explain_followup_stays_documentation(tmp_path):
    """An explain follow-up on GENERATED CODE must still route to the
    Documentation Agent (the downgrade must not fire when real code is
    in the active context)."""
    coord = make_fallback_coordinator(tmp_path)
    coord._active["code"] = (
        "def binary_search(arr, target):\n    low, high = 0, len(arr) - 1\n"
        "    while low <= high:\n        mid = (low + high) // 2\n        return mid\n"
    )
    coord._active["topic"] = "binary search"

    result = coord.handle_task("Explain it in simple words")
    assert result["agent"] == "Documentation Agent"


# ======================================================================
# Q3 regression: PATCH instructions must never leak into the UI
# ======================================================================

BINARY_SEARCH_CODE = (
    "def binary_search(arr, target):\n"
    "    low, high = 0, len(arr) - 1\n"
    "    while low <= high:\n"
    "        mid = (low + high) // 2\n"
    "        if arr[mid] == target:\n"
    "            return mid\n"
    "        elif arr[mid] < target:\n"
    "            low = mid + 1\n"
    "        else:\n"
    "            high = mid - 1\n"
    "    return -1\n"
)


class PatchResponseLLM(FakeLLM):
    """Coding agent answers with PATCH instructions (as the 8B model
    sometimes does for 'optimize' follow-ups) instead of a full code
    dump."""

    def __init__(self, patch_text=None):
        super().__init__()
        self.patch_text = patch_text or (
            "PATCH: binary_search.py\n"
            "REPLACE:\n"
            "        return mid\n"
            "WITH:\n"
            "        return mid  # found!\n"
        )

    def ask(self, prompt):
        low = FakeLLM._to_text(prompt).lower()
        if low.lstrip().startswith("you are an intent classifier"):
            # Reuse FakeLLM's classifier routing ("run" -> execution).
            return super().ask(prompt)
        if "you are an ai coding assistant" in low:
            return self.patch_text
        return super().ask(prompt)


def test_patch_instructions_never_leak_into_coding_response(tmp_path):
    """Q3 regression: when the coding agent answers 'Optimize it' with a
    PATCH block, the patch is applied to the active code and the raw
    PATCH/REPLACE/WITH instructions never appear in the response."""
    memory = Memory()
    short_memory = ShortTermMemory(file_path=str(tmp_path / "stm.json"))
    coord = CoordinatorAgent(PatchResponseLLM(), FakeGuard(), memory, short_memory)
    coord._active["topic"] = "binary search"
    coord._active["code"] = BINARY_SEARCH_CODE

    result = coord.handle_task("Optimize it")

    assert result["agent"] == "Coding Agent"
    resp = result["response"]
    assert "PATCH:" not in resp, "raw PATCH instructions leaked"
    assert "REPLACE:" not in resp, "raw REPLACE instructions leaked"
    assert "WITH:" not in resp, "raw WITH instructions leaked"
    # The patch was applied to the in-memory active code.
    assert "# found!" in resp
    assert "def binary_search" in resp


def test_patch_applied_to_real_file_when_it_exists(tmp_path, monkeypatch):
    """PATCH blocks targeting a real file on disk update that file and
    the response shows the resulting content only."""
    monkeypatch.chdir(tmp_path)
    with open("binary_search.py", "w", encoding="utf-8") as f:
        f.write(BINARY_SEARCH_CODE)

    memory = Memory()
    short_memory = ShortTermMemory(file_path=str(tmp_path / "stm.json"))
    coord = CoordinatorAgent(
        PatchResponseLLM(
            patch_text=(
                "PATCH: binary_search.py\n"
                "REPLACE:\n"
                "        return mid\n"
                "WITH:\n"
                "        return mid  # patched on disk\n"
            )
        ),
        FakeGuard(),
        memory,
        short_memory,
    )
    coord._active["topic"] = "binary search"
    coord._active["code"] = BINARY_SEARCH_CODE

    result = coord.handle_task("Optimize it")

    assert "PATCH:" not in result["response"]
    assert "# patched on disk" in result["response"]
    with open("binary_search.py", encoding="utf-8") as f:
        assert "# patched on disk" in f.read()


def test_execution_response_strips_patch_instructions(tmp_path, monkeypatch):
    """The execution path applies patches but must also hide the raw
    PATCH block from the displayed response."""
    memory = Memory()
    short_memory = ShortTermMemory(file_path=str(tmp_path / "stm.json"))
    coord = CoordinatorAgent(
        PatchResponseLLM(
            patch_text=(
                "PATCH: binary_search.py\n"
                "REPLACE:\n"
                "        return mid\n"
                "WITH:\n"
                "        return mid  # found!\n"
            )
        ),
        FakeGuard(),
        memory,
        short_memory,
    )
    coord.coding.use_tool = lambda task, tool_input: (
        {"success": True, "result": "Hello World"}
    )

    result = coord.handle_task("Run this Python script")

    assert result["agent"] == "Code Executor"
    resp = result["response"]
    assert "PATCH:" not in resp
    assert "REPLACE:" not in resp
    assert "WITH:" not in resp
    assert "Execution Output" in resp
    assert "Hello World" in resp


def test_coding_prose_response_is_retried_for_code(tmp_path):
    """A coding request answered with prose is retried once so the user
    gets code, not a dead end (Q3 re-verification safeguard)."""
    coord = make_coordinator(tmp_path)
    calls = []

    class ProseThenCode(FakeLLM):
        def ask(self, prompt):
            calls.append(FakeLLM._to_text(prompt))
            low = FakeLLM._to_text(prompt).lower()
            if low.lstrip().startswith("you are an intent classifier"):
                return "coding"
            if "you are an ai coding assistant" in low:
                if len(calls) == 1:
                    return "# Please provide the code you would like me to review."
                return "def binary_search(arr, target):\n    return -1\n"
            return super().ask(prompt)

    coord.model = coord.coding.model = coord.decision_engine.model = ProseThenCode()
    result = coord.handle_task("Write Python code for Binary Search.")
    assert result["agent"] == "Coding Agent"
    assert "binary_search" in result["response"]
    assert len(calls) >= 2  # classifier + first coding attempt + retry


def test_coding_code_response_not_retried(tmp_path):
    """A proper code answer is returned unchanged (no wasted retry)."""
    coord = make_coordinator(tmp_path)
    calls = []

    class CodeLLM(FakeLLM):
        def ask(self, prompt):
            calls.append(FakeLLM._to_text(prompt))
            low = FakeLLM._to_text(prompt).lower()
            if low.lstrip().startswith("you are an intent classifier"):
                return "coding"
            return super().ask(prompt)

    coord.model = coord.coding.model = coord.decision_engine.model = CodeLLM()
    result = coord.handle_task("Write a Python function to find factorial")
    assert result["agent"] == "Coding Agent"
    # Only classifier + one coding call (no retry for real code).
    coding_calls = [c for c in calls if "you are an ai coding assistant" in c.lower()]
    assert len(coding_calls) == 1


def test_plain_code_with_word_patch_is_not_stripped():
    """Normal text/code that merely contains the word 'patch' must never
    be removed - only whole-line PATCH: action blocks are."""
    from tools.code_cleaner import strip_action_instructions

    text = (
        "def apply_patch(file, old, new):\n"
        "    # careful: this patch function is real code\n"
        "    return file.replace(old, new)\n"
    )
    assert strip_action_instructions(text) == text.strip()


# ======================================================================
# Q3/Q1 regression: exact word-count enforcement
# ======================================================================


class WordCountLLM(FakeLLM):
    """Returns scripted responses for the word-count correction passes."""

    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)

    def ask(self, prompt):
        if self.responses:
            return self.responses.pop(0)
        return "fallback"


def test_enforce_word_count_exact_rewrites_until_target(tmp_path):
    """'exactly N words' is enforced: an off-target response is rewritten
    (up to three passes) until it lands inside the tight band."""
    coord = make_coordinator(tmp_path)
    # Nine words, target five -> outside the exact band (5 +/- 2).
    nine_words = "one two three four five six seven eight nine"
    five_words = "alpha beta gamma delta epsilon"
    coord.model = WordCountLLM([five_words])

    out = coord._enforce_word_count(nine_words, 5, exact=True)
    assert out == five_words
    assert len(out.split()) == 5


def test_enforce_word_count_exact_keeps_closest_after_failed_passes(tmp_path):
    coord = make_coordinator(tmp_path)
    nine_words = "one two three four five six seven eight nine"
    # Both corrections still miss the band (3 and 11 words); the closer
    # one (3 vs 5) must be kept.
    coord.model = WordCountLLM(["a b c", "x y z q r s t u v w k"])  # 3, 11

    out = coord._enforce_word_count(nine_words, 5, exact=True)
    assert len(out.split()) == 3  # closest to the target


def test_enforce_word_count_approximate_uses_loose_band(tmp_path):
    """Non-exact requests keep the plus/minus-five band (no correction
    when already close)."""
    coord = make_coordinator(tmp_path)
    seven_words = "one two three four five six seven"
    coord.model = WordCountLLM([])

    # 7 words vs target 5: |7-5|=2 <= 5 -> accepted without any rewrite.
    out = coord._enforce_word_count(seven_words, 5, exact=False)
    assert out == seven_words


def test_exact_word_count_flows_through_handle_task(tmp_path):
    """The exact flag detected from the user request reaches
    _enforce_word_count (integration)."""
    from agents.response_directives import extract_directives

    d = extract_directives("Explain recursion for a beginner in exactly 80 words")
    assert d["word_count"] == 80
    assert d.get("word_count_exact") is True


def test_count_words_ignores_list_markers():
    """Bullet/list markers are formatting, not words: an 80-word bullet
    answer must count as 80, not 80 + number of bullets (Q16 regression)."""
    from agents.coordinator import count_words

    bullets = "\n".join("- one two three" for _ in range(7))  # 21 content words
    assert count_words(bullets) == 21
    assert count_words("1. alpha beta\n2. gamma delta") == 4
    assert count_words("* a b c") == 3
    assert count_words("plain sentence with five words") == 5
    # Markers mid-line still count as words (only leading markers are
    # formatting).
    assert count_words("a - b") == 3


def test_prose_rewrite_followup_not_pinned_to_coding(tmp_path):
    """Q17 regression: 'rewrite it for an experienced programmer' on a
    PROSE conversation must not be forced into the Coding Agent."""
    coord = make_coordinator(tmp_path)
    coord._active["topic"] = "recursion"
    coord._active["code"] = None

    decision = coord._override_followup_decision(
        "Take the previous recursion explanation and rewrite it for an "
        "experienced programmer using technical terminology in exactly 80 words.",
        "followup",
        "documentation",
    )
    assert decision == "documentation"


def test_code_followup_still_pinned_to_coding(tmp_path):
    """Code work ('Optimize the code', 'Convert it to Java') keeps the
    deterministic Coding pin when real code is in context."""
    coord = make_coordinator(tmp_path)
    coord._active["topic"] = "binary search"
    coord._active["code"] = "def binary_search(arr, target):\n    pass\n"

    assert coord._override_followup_decision(
        "Optimize the code", "followup", "chat"
    ) == "coding"
    assert coord._override_followup_decision(
        "Convert it to Java", "followup", "chat"
    ) == "coding"
    # Prose work on the same code context: 'explain' stays with docs.
    assert coord._override_followup_decision(
        "Improve the explanation", "followup", "chat"
    ) == "chat"


# ======================================================================
# Section 6 - static metrics are hidden by default (opt-in only)
# ======================================================================

def test_code_analysis_hides_static_metrics_by_default(tmp_path):
    """A plain code-analysis request shows the clean LLM analysis - no
    deterministic metrics dashboard (quality score, cyclomatic
    complexity, unused imports, ...)."""
    coord = make_coordinator(tmp_path)
    result = coord.handle_task(
        "Analyze this code\n```python\ndef add(a, b):\n    return a + b\n```"
    )

    assert result["agent"] == "Code Analysis Agent"
    assert "Code Quality" in result["response"]
    assert "Static Metrics" not in result["response"]
    assert "Cyclomatic complexity" not in result["response"]
    assert "Detailed Analysis (LLM)" not in result["response"]


def test_code_analysis_shows_metrics_when_explicitly_requested(tmp_path):
    """\"show the static metrics\" opts into the deterministic block."""
    coord = make_coordinator(tmp_path)
    result = coord.handle_task(
        "Analyze this code and show the static metrics\n"
        "```python\ndef add(a, b):\n    return a + b\n```"
    )

    assert result["agent"] == "Code Analysis Agent"
    assert "Static Metrics" in result["response"]
    assert "Cyclomatic complexity" in result["response"]
    assert "Code Quality" in result["response"]


def test_explain_the_bug_followup_routes_to_debugging(tmp_path):
    """Regression: "Explain the bug" (singular) after a project upload is
    a debugging request - it must reach the Debugging Agent (not the
    Documentation Agent) and keep the project context."""
    coord = make_fallback_coordinator(tmp_path)
    coord._active["topic"] = "sample project"
    coord._active["project_root"] = None
    coord._active["code"] = None
    coord._active["files"] = ["project: Sample.zip"]

    # "the bug" refers back to the active project -> follow-up, not a
    # new topic, so project context is retained.
    assert coord._classify_followup("Explain the bug") == "followup"
    assert coord.handle_task("Explain the bug")["agent"] == "Debugging Agent"
    assert coord.handle_task("Find a bug")["agent"] == "Debugging Agent"


# ======================================================================
# No-ZIP safety: project requests without any project context must never
# scan the assistant's own workspace - they ask for the project files.
# ======================================================================

def test_project_requests_without_context_ask_for_upload(tmp_path):
    """All project-level phrasings with NO uploaded project / generated
    code return the friendly upload prompt instead of analyzing the
    assistant's own workspace."""
    coord = make_fallback_coordinator(tmp_path)
    for req in (
        "Review this project",
        "Analyze this project",
        "Create a plan for this project",
        "Generate documentation for this project",
        "Find bugs in this project",
        "Fix the bug in this project",
        "Review and fix this project",
    ):
        result = coord.handle_task(req)
        assert "upload the project" in result["response"].lower(), req
        assert result["agent"] == "Assistant", req


def test_project_request_with_generated_code_still_works(tmp_path):
    """After BUILDING an app (generated code in context), a project
    request must NOT ask for an upload - the generated app IS the user's
    project and the reviewer receives it."""
    coord = make_fallback_coordinator(tmp_path)
    coord._active["code"] = "def hospital():\n    return 'ok'\n"
    coord._active["workflow"] = "Hospital Management System"
    captured = []
    orig = coord.reviewer.review
    coord.reviewer.review = lambda code: (captured.append(code) or "review done")
    try:
        result = coord.handle_task("Review this project")
    finally:
        coord.reviewer.review = orig
    assert "upload the project" not in result["response"].lower()
    assert result["agent"] == "Reviewer Agent"
    assert captured and "def hospital" in captured[0]


def test_build_request_not_treated_as_project_review(tmp_path):
    """\"Build a project management app\" is a BUILD request - it must not
    trigger the no-project upload prompt (the app is generated)."""
    coord = make_fallback_coordinator(tmp_path)
    result = coord.handle_task("Build a project management app")
    assert result["agent"] == "Collaborative Workflow"
    assert "upload the project" not in result["response"].lower()


def test_make_corrected_code_simpler_is_coding_followup(tmp_path):
    """\"Make the corrected code simpler\" after a project review+fix must
    be a follow-up on that code and route to the Coding Agent (not the
    Reviewer), keeping the corrected code in context."""
    coord = make_fallback_coordinator(tmp_path)
    coord._active["topic"] = "sample project"
    coord._active["code"] = (
        "def divide(a, b):\n    if b == 0:\n        return None\n    return a / b\n"
    )
    coord._active["workflow"] = "Project Review & Fix Workflow"

    assert coord._classify_followup("Make the corrected code simpler") == "followup"
    assert coord.handle_task("Make the corrected code simpler")["agent"] == (
        "Coding Agent"
    )


# =====================================================================
# Normal routing regression (image-upload feature removed): code analysis,
# project analysis and file attachments keep their original behavior.
# =====================================================================

def test_analyze_code_routes_to_code_analysis(tmp_path):
    """\"Analyze this Python code\" keeps its Code Analysis routing even
    when an uploaded project is active."""
    coord = make_coordinator(tmp_path)
    coord._active["code"] = "print('x')"
    coord._active["project_root"] = str(tmp_path)
    followup = coord._classify_followup("Analyze this Python code.")
    decision = coord._override_followup_decision(
        "Analyze this Python code.", followup, "code_analysis",
        raw_task="Analyze this Python code.",
    )
    assert decision == "code_analysis"


def test_analyze_function_routes_to_code_analysis(tmp_path):
    """\"Analyze this function\" is a CODE request, not a project request:
    it must keep its Code Analysis routing."""
    coord = make_coordinator(tmp_path)
    coord._active["code"] = "def f(): pass"
    coord._active["project_root"] = str(tmp_path)
    followup = coord._classify_followup("Analyze this function.")
    decision = coord._override_followup_decision(
        "Analyze this function.", followup, "code_analysis",
        raw_task="Analyze this function.",
    )
    assert decision == "code_analysis"


def test_analyze_project_routes_to_project_analysis(tmp_path):
    """\"Analyze this project\" must route to the Project Analyzer, never
    to Code Analysis, when an uploaded project is in context."""
    coord = make_coordinator(tmp_path)
    # Active project context (uploaded ZIP kept for follow-ups).
    coord._active["files"] = ["project: sample.zip"]
    coord._active["project_root"] = str(tmp_path)
    followup = coord._classify_followup("Analyze this project.")
    assert followup == "followup"
    decision = coord._override_followup_decision(
        "Analyze this project.", followup, "code_analysis",
        raw_task="Analyze this project.",
    )
    assert decision == "project"


class DenyGuard(FakeGuard):
    """Guard that blocks LLM calls, forcing the Project Analyzer's
    deterministic static-summary path (no LLM needed in tests)."""

    def can_call(self):
        return False


def test_analyze_project_with_zip_routes_to_project_analyzer(tmp_path):
    """End-to-end: an uploaded ZIP + \"Analyze this project\" runs the
    Project Analyzer (correct agent label), reads the uploaded project's
    ACTUAL files, and returns a non-empty response - never Code Analysis."""
    proot = tmp_path / "proj"
    proot.mkdir()
    (proot / "main.py").write_text(
        "def add(a, b):\n    return a + b\n\nprint(add(2, 3))\n"
    )
    memory = Memory()
    short_memory = ShortTermMemory(file_path=str(tmp_path / "stm.json"))
    coord = CoordinatorAgent(FakeLLM(), DenyGuard(), memory, short_memory)
    task = (
        "Analyze this project.\n\n"
        f"[Attached project: sample.zip] (extracted to: {proot})\n"
        "Project files:\n- app/main.py\n- README.md"
    )
    result = coord.handle_task(task)
    assert result["agent"] == "Project Analyzer", result["agent"]
    assert result.get("response"), "project analysis must be non-empty"
    # The analyzer must have read the uploaded project's actual files.
    assert "main.py" in result["response"]


def test_attached_file_first_turn_is_followup_context(tmp_path):
    """A message carrying an uploaded FILE is attachment-context work: it
    classifies as a follow-up even on the very first turn."""
    coord = make_fallback_coordinator(tmp_path)
    task = "Explain this code.\n\n[Attached file: hello.py]"
    assert coord._classify_followup(task) == "followup"


class DocumentationMisclassifyLLM(FakeLLM):
    """Classifier that answers a VALID but wrong category (documentation)
    for analyze-the-code requests - proves the deterministic pre-LLM pin
    wins over a confident LLM misclassification."""

    def ask(self, prompt):
        low = FakeLLM._to_text(prompt).lower()
        if low.lstrip().startswith("you are an intent classifier"):
            task = self._user_request(prompt)
            if ("python code" in task or "this function" in task
                    or "this code" in task):
                return "documentation"
        return super().ask(prompt)


def test_analyze_code_llm_misclassification_still_routes_to_code_analysis(tmp_path):
    """Regression: a real LLM once classified \"Analyze this Python code\" as
    documentation (a follow-up with no attachment marker -> new_topic), so
    the deterministic follow-up override never ran and the request reached
    the Documentation Agent. The decision engine must pin explicit
    analyze-the-code requests to Code Analysis BEFORE trusting the LLM."""
    from agents.decision_engine import DecisionEngine
    coord = make_coordinator(tmp_path)
    llm = DocumentationMisclassifyLLM()
    de = DecisionEngine(model=llm, guard=coord.guard)
    assert de.decide("Analyze this Python code") == "code_analysis"
    assert de.decide("Analyze this function") == "code_analysis"
    # A code snippet pasted in a fenced block is still code analysis.
    assert (
        de.decide("Analyze this code\n```python\ndef add(a, b): return a + b\n```")
        == "code_analysis"
    )


def test_analyze_code_with_pasted_snippet_and_attached_project_stays_code_analysis(tmp_path):
    """Regression (live): \"Analyze this Python code\" followed by a pasted
    snippet and an attached project listing was misrouted to Documentation.
    The \"add\" inside the code fence (def add(...)) plus \"README.md\" in
    the project's file list matched the documentation-work heuristic, and
    a confident LLM agreed. Deterministic routing must use only the user's
    own words, so this must stay Code Analysis - never Documentation."""
    from agents.decision_engine import DecisionEngine
    proot = tmp_path / "proj"
    proot.mkdir()
    (proot / "main.py").write_text("def add(a, b):\n    return a + b\n")
    task = (
        "Analyze this Python code:\n"
        "```python\n"
        "def add(a, b):\n    return a + b\n"
        "```\n"
        f"[Attached project: proj_check.zip] (extracted to: {proot})\n"
        "Project files:\n"
        "- app/main.py (105 B)\n"
        "- README.md (40 B)"
    )
    coord = make_coordinator(tmp_path)
    # The LLM confidently (but wrongly) says documentation.
    de = DecisionEngine(model=DocumentationMisclassifyLLM(), guard=coord.guard)
    assert de.decide(task) == "code_analysis"
    assert coord._classify_followup(task) == "followup"
    assert coord._override_followup_decision(
        coord._strip_app_context(task), "followup", "documentation",
        raw_task=task,
    ) == "code_analysis"
    # End-to-end: the agent label must be Code Analysis Agent.
    memory = Memory()
    short_memory = ShortTermMemory(file_path=str(tmp_path / "stm.json"))
    e2e = CoordinatorAgent(FakeLLM(), DenyGuard(), memory, short_memory)
    result = e2e.handle_task(task)
    assert result["agent"] == "Code Analysis Agent", result["agent"]


# ======================================================================
# Error-handling follow-ups ("Also handle invalid non-numeric input.")
# must stay in the active debugging conversation - they were being
# classified as new topics, losing context, and misrouted to the Patch
# Tool (which then hallucinated a file name like calculator.py).
# ======================================================================

def test_error_handling_followup_routes_to_debugging(tmp_path):
    """Regression (live): \"Also handle invalid non-numeric input.\" after
    a divide() debugging session was classified new_topic (\"handle\" was
    not a recognized follow-up verb), the active code context was
    dropped, and the LLM's \"patch\" classification sent it to the Patch
    Tool, which invented a calculator.py file. It must instead stay in
    the conversation and reach the Debugging Agent with the previous
    code retained."""
    coord = make_fallback_coordinator(tmp_path)
    coord._active["topic"] = "divide function"
    coord._active["code"] = "def divide(a, b):\n    return a / b\nprint(divide(10, 0))"
    coord._active["workflow"] = "debug"

    task = "Also handle invalid non-numeric input."
    assert coord._classify_followup(task) == "followup"
    decision = coord.decision_engine.decide(task)
    assert coord._override_followup_decision(
        coord._strip_app_context(task), "followup", decision
    ) == "debug"

    # End-to-end: Debugging Agent, and the divide() code actually reaches it.
    captured = {}
    orig = coord.debugging.debug_code
    coord.debugging.debug_code = lambda t, ctx="": (
        captured.update(task=t, ctx=ctx) or "corrected"
    )
    try:
        result = coord.handle_task(task)
    finally:
        coord.debugging.debug_code = orig
    assert result["agent"] == "Debugging Agent", result["agent"]
    # The active-context block (with the previous divide() code) must be
    # appended to the task the Debugging Agent receives.
    assert "divide" in captured.get("task", ""), (
        "previous code context must be retained"
    )
    assert "[Active context]" in captured.get("task", "")


def test_error_handling_fresh_request_is_new_topic(tmp_path):
    """The same phrase as a FIRST message (no active context) must be
    classified normally - not hijacked into the follow-up path."""
    coord = make_fallback_coordinator(tmp_path)
    assert coord._classify_followup("Also handle invalid non-numeric input.") == "new_topic"
    result = coord.handle_task("Handle invalid non-numeric input.")
    assert result["agent"] != "Patch Tool", result["agent"]


# ======================================================================
# Planner routing: "step-by-step plan ... building", "development plan"
# and plan-expansion follow-ups ("Break step 3 into smaller tasks") must
# reach the Planner - not the Build Workflow or Coding Agent.
# ======================================================================

def test_planning_requests_route_to_planner(tmp_path):
    coord = make_fallback_coordinator(tmp_path)
    for req in (
        "Create a step-by-step plan for building a Python command-line "
        "calculator with add, subtract, multiply, and divide operations.",
        "Create a development plan for adding memoization.",
        "Design a roadmap for the API.",
    ):
        decision = coord.decision_engine.decide(req)
        assert decision == "planner", (req, decision)


def test_break_step_followup_stays_planner(tmp_path):
    """Regression: \"Break step 3 into smaller implementation tasks\" is a
    plan-expansion follow-up - it must stay a follow-up (context kept)
    and reach the Planner, not be read as code work."""
    coord = make_fallback_coordinator(tmp_path)
    coord._active["topic"] = "calculator plan"
    coord._active["code"] = "Step 1..3 plan"
    coord._active["workflow"] = "calculator"

    req = "Break step 3 into smaller implementation tasks."
    assert coord._classify_followup(req) == "followup"
    decision = coord.decision_engine.decide(req)
    assert coord._override_followup_decision(
        coord._strip_app_context(req), "followup", decision
    ) == "planner"
    assert coord.handle_task(req)["agent"] == "Planner Agent"


def test_improvement_question_is_code_analysis_not_coding(tmp_path):
    """\"What is the most important improvement you would make to this
    file?\" asks for ANALYSIS of existing work - it must reach Code
    Analysis, while imperative modify requests (\"Make the corrected
    code simpler\") stay with the Coding Agent."""
    coord = make_fallback_coordinator(tmp_path)
    coord._active["topic"] = "main.py"
    coord._active["files"] = ["main.py"]
    coord._active["code"] = "from agents.coordinator import CoordinatorAgent\n..."

    req = "What is the most important improvement you would make to this file?"
    assert coord._classify_followup(req) == "followup"
    assert coord.handle_task(req)["agent"] == "Code Analysis Agent"

    simpler = "Make the corrected code simpler."
    decision = coord.decision_engine.decide(simpler)
    assert coord._override_followup_decision(
        coord._strip_app_context(simpler), "followup", decision
    ) == "coding"
