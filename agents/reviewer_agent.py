from tools.tool_manager import ToolManager
from prompts.reviewer_prompt import REVIEWER_PROMPT


class ReviewerAgent:

    def __init__(self, model, guard):

        self.model = model
        self.guard = guard
        self.tool_manager = ToolManager()


    def use_tool(self, task, tool_input):

        return self.tool_manager.execute_tool(
            task,
            tool_input
        )


    def review(self, code):

        if self.guard.can_call():

            self.guard.register_call()

            prompt = REVIEWER_PROMPT.format(
                input=code
            )

            return self.model.ask(prompt)

        return "LLM limit reached in ReviewerAgent"