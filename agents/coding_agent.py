


class CodingAgent:
    def __init__(self, model, guard):
        self.model = model
        self.guard = guard

    def solve_task(self, task):
        if self.guard.can_call():
            self.guard.register_call()
            return self.model.ask(task)
        return "LLM limit reached in CodingAgent"