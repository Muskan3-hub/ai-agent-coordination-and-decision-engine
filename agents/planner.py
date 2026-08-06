from tools.tool_manager import ToolManager
from prompts.planner_prompt import PLANNER_PROMPT


class Planner:

    def __init__(self, model, guard):
        self.model = model
        self.guard = guard
        self.tool_manager = ToolManager()
    def use_tool(self, task, tool_input):

        return self.tool_manager.execute_tool(task, tool_input)

    def execute(self, user_input, context=""):

        task = f"""
Previous Conversation:
{context}

User Request:
{user_input}
"""

        if not self.guard.can_call():
            return "LLM limit reached in Planner"

        self.guard.register_call()

        prompt = PLANNER_PROMPT.format_messages(input=task)

        return self.model.ask(prompt)