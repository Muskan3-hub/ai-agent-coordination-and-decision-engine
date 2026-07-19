from tools.tool_manager import ToolManager
from prompts.coding_prompt import CODING_PROMPT

class CodingAgent:

    def __init__(self, model, guard):
        self.model = model

        self.guard = guard
        self.tool_manager = ToolManager()
    
    def use_tool(self, task, tool_input):

        return self.tool_manager.execute_tool(task, tool_input)



    def solve_task(self, task):

        if self.guard.can_call():
            self.guard.register_call()
            prompt = CODING_PROMPT.format_messages(input=task)
            return self.model.ask(prompt)
        return "LLM limit reached in CodingAgent"