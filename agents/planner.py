from prompts.planner_prompt import PLANNER_PROMPT


class Planner:

    def __init__(self, model, guard):
        self.model = model
        self.guard = guard

    def execute(self, user_input, context=""):

        self.guard.reset()

        task = f"""
Previous Conversation:
{context}

User Request:
{user_input}
"""

        prompt = PLANNER_PROMPT.format_messages(input=task)

        return self.model.ask(prompt)