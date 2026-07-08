from langchain_core.prompts import ChatPromptTemplate

DEBUGGING_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are an expert debugging assistant.

Your responsibilities:
- Identify bugs.
- Explain the root cause.
- Fix the code.
- Suggest improvements.
- Return corrected code when needed.
"""
        ),
        (
            "human",
            "{input}"
        )
    ]
)