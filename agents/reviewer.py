
from prompts.reviewer_prompt import REVIEWER_PROMPT


class Reviewer:
    def __init__(self, model, guard):
        self.model = model
        self.guard = guard

    def execute(self, code):
        if self.guard.can_call():
            self.guard.register_call()

            prompt = REVIEWER_PROMPT.format_messages(input=code)

            return self.model.ask(prompt)

        return "LLM limit reached in Reviewer"