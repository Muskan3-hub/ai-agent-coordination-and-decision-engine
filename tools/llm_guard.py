class LLMGuard:
    def __init__(self):
        self.call_count = 0
        self.max_calls_per_request = 8 # control quota usage (classifier + workflow)

    def can_call(self):
        return self.call_count < self.max_calls_per_request

    def register_call(self):
        self.call_count += 1

    def reset(self):
        self.call_count = 0