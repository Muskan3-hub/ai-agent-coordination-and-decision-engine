"""Code cleaning utilities (Issue 15)."""


def strip_fences(text):
    text = text.strip()
    text = text.replace("```python", "")
    text = text.replace("```", "")
    if text.startswith("python"):
        text = text[6:].strip()
    return text.strip()


def clean_code(text):
    text = strip_fences(text)
    if text.startswith("FILE:"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:].strip()
        else:
            parts = text.split(".py", 1)
            if len(parts) == 2:
                text = parts[1].strip()
    text = text.replace("def init(", "def __init__(")
    text = text.replace(
        'if name == "main":',
        'if __name__ == "__main__":'
    )
    return text.strip()
