from langchain_core.prompts import ChatPromptTemplate

PROJECT_ANALYZER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a senior software architect.

Analyze the project and explain:
- Project purpose
- Folder structure
- Important files
- Code quality
- Architecture
- Possible improvements
"""
        ),
        (
            "human",
            "{input}"
        )
    ]
)