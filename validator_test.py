from tools.action_validator import ActionValidator


result = ActionValidator.validate_patch(
    "test.py",
    'print("Hi")'
)

print(result)