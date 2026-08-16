from agents.decision_engine import DecisionEngine


class StubModel:
    def __init__(self, reply):
        self.reply = reply

    def ask(self, prompt):
        return self.reply


class StubGuard:
    def __init__(self):
        self.count = 0

    def can_call(self):
        return True

    def register_call(self):
        self.count += 1

    def reset(self):
        self.count = 0


def test_llm_classification():
    engine = DecisionEngine(
        model=StubModel("memory_store"),
        guard=StubGuard(),
        use_llm=True,
    )
    assert engine.decide("My name is Muskan") == "memory_store"


def test_llm_classification_returns_unknown_falls_back():
    engine = DecisionEngine(
        model=StubModel("something-bogus"),
        guard=StubGuard(),
        use_llm=True,
    )
    # LLM answer invalid -> keyword fallback kicks in
    assert engine.decide("Build a calculator application") == "workflow"


def test_keyword_fallback_memory_store():
    engine = DecisionEngine(use_llm=False)
    assert engine.decide("My name is Muskan") == "memory_store"
    assert engine.decide("I like pizza") == "memory_store"


def test_keyword_fallback_memory_recall():
    engine = DecisionEngine(use_llm=False)
    assert engine.decide("What is my name?") == "memory_recall"
    assert engine.decide("Do you remember my favorite color?") == "memory_recall"


def test_keyword_fallback_workflow():
    engine = DecisionEngine(use_llm=False)
    assert engine.decide("Build a calculator application") == "workflow"
    assert engine.decide("Could you develop software that manages books?") == "workflow"


def test_keyword_fallback_chat():
    engine = DecisionEngine(use_llm=False)
    assert engine.decide("What is AI?") == "chat"
    assert engine.decide("Who is Alan Turing?") == "chat"
    assert engine.decide("Hi there!") == "chat"


def test_concept_explain_is_chat_but_code_explain_is_documentation():
    engine = DecisionEngine(use_llm=False)
    # Issue 4: concept questions are chat, even in fallback mode
    assert engine.decide("Explain recursion") == "chat"
    assert engine.decide("Describe recursion") == "chat"
    # Explaining a specific piece of code is documentation (spec: explain
    # -> Documentation Agent; analysis verbs stay code analysis).
    assert engine.decide("Explain this code") == "documentation"
    assert engine.decide("Explain this source code") == "documentation"
    # Documenting a function stays documentation
    assert engine.decide("Document this function") == "documentation"
    # Complexity questions about code are code analysis
    assert engine.decide("Explain time complexity") == "code_analysis"


def test_keyword_fallback_code_analysis():
    engine = DecisionEngine(use_llm=False)
    assert engine.decide("Analyze this code") == "code_analysis"
    assert engine.decide("Review this Python file") == "review"
    assert engine.decide("Check code quality") == "code_analysis"
    assert engine.decide("Find issues in this code") == "code_analysis"
    assert engine.decide("Review this code") == "review"
    # Project-level analysis stays project
    assert engine.decide("Analyze this project") == "project"


def test_keyword_fallback_coding():
    engine = DecisionEngine(use_llm=False)
    assert engine.decide("Write a Python function to find factorial") == "coding"


def test_keyword_fallback_tools():
    engine = DecisionEngine(use_llm=False)
    assert engine.decide("Analyze this project") == "project"
    assert engine.decide("Fix this bug in my code") == "debug"
    assert engine.decide("Read app.py") == "file"
    assert engine.decide("Run this python code") == "execution"


def test_memory_override_wins_even_when_llm_says_coding():
    # LLM misclassifies, but the unambiguous personal-info fast path wins
    engine = DecisionEngine(
        model=StubModel("coding"),
        guard=StubGuard(),
        use_llm=True,
    )
    assert engine.decide("My name is Muskan") == "memory_store"
