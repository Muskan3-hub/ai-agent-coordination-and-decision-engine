from tools.tool_manager import ToolManager
from prompts.debugging_prompt import DEBUGGING_PROMPT


class DebuggingAgent:
    def __init__(self, model, guard):
        self.tool_manager = ToolManager()
        self.model = model
        self.guard = guard
    def use_tool(self, task, tool_input):

        return self.tool_manager.execute_tool(task, tool_input)

    def debug_code(self, task, context=""):
        if self.guard.can_call():
            self.guard.register_call()

            if context:
                task = (
                    "Previous Conversation:\n"
                    f"{context}\n\n"
                    f"User Request:\n{task}"
                )

            prompt = DEBUGGING_PROMPT.format_messages(input=task)

            return self.model.ask(prompt)

        return "LLM limit reached in DebuggingAgent"
    