from langchain_core.prompts import ChatPromptTemplate

PLANNER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a software project planner.

Break complex tasks into logical steps.

Return:
1. Objectives
2. Required files
3. Implementation steps
4. Expected output
"""
        ),
        (
            "human",
            "{input}"
        )
    ]
)