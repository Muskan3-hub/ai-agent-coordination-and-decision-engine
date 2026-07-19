from tools.tool_manager import ToolManager
from prompts.documentation_prompt import DOCUMENTATION_PROMPT


class DocumentationAgent:
    def __init__(self, model, guard):
        self.model = model
        self.guard = guard
        self.tool_manager = ToolManager()
    def use_tool(self, task, tool_input):

        return self.tool_manager.execute_tool(task, tool_input)

    def explain(self, task):
        if self.guard.can_call():
            self.guard.register_call()

            prompt = DOCUMENTATION_PROMPT.format_messages(input=task)

            return self.model.ask(prompt)

        return "LLM limit reached in DocumentationAgent"