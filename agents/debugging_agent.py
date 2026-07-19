from tools.tool_manager import ToolManager
from prompts.debugging_prompt import DEBUGGING_PROMPT


class DebuggingAgent:
    def __init__(self, model, guard):
        self.tool_manager = ToolManager()
        self.model = model
        self.guard = guard

    def debug_code(self, task):
        if self.guard.can_call():
            self.guard.register_call()

            prompt = DEBUGGING_PROMPT.format_messages(input=task)

            return self.model.ask(prompt)

        return "LLM limit reached in DebuggingAgent"
    def use_tool(self, task, tool_input):

        tool = self.tool_manager.select_tool(task)


        if tool is None:
            return "No suitable tool found."


        return tool.execute(tool_input)