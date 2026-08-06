import os

PROTECTED_FILES = [
    "app.py",
    "main.py"
]


def check_file_permission(file_path):

    # os.path.basename handles both "/" and "\\" so protected-file
    # checks work on Windows paths too (Issue: split("/") missed
    # backslash paths).
    filename = os.path.basename(file_path)

    if filename in PROTECTED_FILES:
        raise Exception(
            f"{filename} is protected and cannot be modified"
        )