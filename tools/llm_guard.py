class LLMGuard:
    def __init__(self):
        self.call_count = 0
        self.max_calls_per_request = 8 # control quota usage (classifier + workflow)

    def can_call(self):
        return self.call_count < self.max_calls_per_request

    def register_call(self):
        self.call_count += 1
        # Internal monitoring (Milestone 4) - never surfaced in the UI.
        try:
            from monitoring.metrics import get_metrics
            get_metrics().record_llm()
        except Exception:
            pass

    def reset(self):
        self.call_count = 0