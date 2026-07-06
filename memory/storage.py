import json
import os

# Path to history.json
HISTORY_FILE = os.path.join(os.path.dirname(__file__), "history.json")


def load_history():
    """Load conversation history from history.json."""
    if not os.path.exists(HISTORY_FILE):
        return []

    with open(HISTORY_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def save_history(history):
    """Save conversation history to history.json."""
    with open(HISTORY_FILE, "w", encoding="utf-8") as file:
        json.dump(history, file, indent=4)