from langchain_core.prompts import ChatPromptTemplate

REVIEWER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a senior software reviewer.

Review code for:
- Bugs
- Readability
- Performance
- Security
- Best practices

Provide constructive suggestions.
"""
        ),
        (
            "human",
            "{input}"
        )
    ]
)