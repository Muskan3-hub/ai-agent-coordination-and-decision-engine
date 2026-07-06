class Planner:

    def __init__(self, model, guard):
        self.model = model
        self.guard = guard

    def execute(self, user_input, context=""):

        self.guard.reset()

        prompt = f"""
You are an expert AI software planning agent.

Break the user's request into a clear execution plan.

Rules:
- Return ONLY the plan.
- Do NOT write any code.
- Keep the plan concise.
- Number each step.
- Focus on how to solve the task.

Previous Conversation:
{context}

User Request:
{user_input}

Format:
1.
2.
3.
"""

        return self.model.ask(prompt)