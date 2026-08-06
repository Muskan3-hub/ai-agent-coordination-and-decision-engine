from prompts.chat_prompt import CHAT_PROMPT


class ChatAgent:
    """Handles general conversation (Issue 4). Never generates code."""

    def __init__(self, model, guard):
        self.model = model
        self.guard = guard

    def answer(self, task, context=""):
        if not self.guard.can_call():
            return "LLM limit reached in ChatAgent"

        self.guard.register_call()

        prompt = CHAT_PROMPT.format_messages(
            input=task,
            context=context
        )

        return self.model.ask(prompt)
