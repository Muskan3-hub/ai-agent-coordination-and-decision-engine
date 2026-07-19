PROTECTED_FILES = [
    "app.py",
    "main.py"
]


def check_file_permission(file_path):

    filename = file_path.split("/")[-1]

    if filename in PROTECTED_FILES:
        raise Exception(
            f"{filename} is protected and cannot be modified"
        )