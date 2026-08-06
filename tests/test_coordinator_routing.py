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

        # Intent classifier prompt
        if "intent classifier" in low:
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

        # Code analysis agent prompt
        if "code analysis agent" in low:
            return "### Code Quality Report\nScore: 88/100"

        # Coding agent task: returns two FILE:-wrapped code blocks
        # (matches the coordinator's coding prompt "You are an AI coding
        # assistant.") so multi-file responses are exercised too.
        if "you are an ai coding assistant" in low:
            return (
                'FILE: generated_program.py\nprint("hello")' +
                '\n\nFILE: helper.py\nprint("world")'
            )

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
    # Task 7: code analysis is now a pipeline stage
    assert "code_analysis" in result["workflow"]


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
