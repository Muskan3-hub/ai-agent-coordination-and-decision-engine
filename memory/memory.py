from memory.storage import load_history, save_history


class Memory:
    def __init__(self):
        self.history = load_history()

    def get_history(self):
        return self.history
    
    def get_recent_context(self,limit=5):
        """
        Returns the last few conversations as a string
        """
        if not self.history:
            return "No previous conversation."
        recent = self.history[-limit:]
        context=""
        for chat in recent:
            context+= f"User:{chat['user']}\n"
            context+= f"Assistant:{chat['assistant']}\n\n"
        return context
    
    def add_conversation(self, user_message, assistant_message):
        # Avoid duplicate consecutive entries (Issue 11)
        if (
            self.history
            and self.history[-1].get("user") == user_message
            and self.history[-1].get("assistant") == assistant_message
        ):
            return

        self.history.append(
            {
                "user": user_message,
                "assistant": assistant_message
            }
        )
        save_history(self.history)

    def clear_history(self):
        self.history = []
        save_history(self.history)
    