from langchain_core.prompts import ChatPromptTemplate

DOCUMENTATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a technical documentation expert.

Your responsibilities:
- Explain code clearly.
- Describe functions and classes.
- Generate documentation.
- Keep explanations concise and easy to understand.
"""
        ),
        (
            "human",
            "{input}"
        )
    ]
)