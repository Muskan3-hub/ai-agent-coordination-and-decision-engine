"""Code cleaning utilities (Issue 15)."""

import re

# A PATCH action block emitted by the coding agent, e.g.:
#
#   PATCH: binary_search.py
#   REPLACE:
#   <old code>
#   WITH:
#   <new code>
#
# The whole block (from the PATCH: header through the WITH: payload) is an
# internal tool command. It must be executed by the Patch Tool and stripped
# from the user-visible response - never shown to the user. The block may
# span multiple lines and may be followed by prose, another PATCH block or
# a FILE: block. Anchored at line start so normal prose that merely
# contains the word "patch" is never touched.
_PATCH_BLOCK_RE = re.compile(
    r"(?:^|\n)\s*PATCH:\s*\S+[^\n]*(?:\n(?!\s*(?:PATCH:|FILE:))[^\n]*)*",
    re.IGNORECASE,
)

# Whole-line FILE: headers from multi-file code output ("FILE: app.py").
_FILE_HEADER_RE = re.compile(r"(?m)^\s*FILE:\s*[^\n]*\n?")


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


def has_patch_instructions(text):
    """True when the model output carries PATCH tool instructions that
    must be executed (and hidden) instead of displayed."""
    return bool(re.search(r"(?:^|\n)\s*PATCH:\s*\S+", text or "", re.IGNORECASE))


def strip_action_instructions(text):
    """Remove tool/action instruction blocks from model output.

    Strips PATCH:/REPLACE:/WITH: blocks and FILE: headers so only
    user-facing content remains. Internal tool commands (patches, file
    save instructions) are never part of the answer the user should see.

    Only whole-line action markers are matched - normal prose or code
    that happens to contain the word "patch" is never touched.
    """
    if not text:
        return text
    text = _FILE_HEADER_RE.sub("", text)
    text = _PATCH_BLOCK_RE.sub("", text)
    return text.strip()
