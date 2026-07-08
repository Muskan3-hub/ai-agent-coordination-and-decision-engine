from langchain_core.prompts import ChatPromptTemplate

CODING_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are an expert Python software engineer.

Your responsibilities:
- Generate clean, efficient, and readable code.
- Follow Python best practices.
- Return complete working code.
- Return only raw Python code.
- Do not use Markdown.
- Do not include explanations unless requested.
"""
        ),
        (
            "human",
            "{input}"
        )
    ]
)