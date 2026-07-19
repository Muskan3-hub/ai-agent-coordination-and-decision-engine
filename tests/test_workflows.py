from tools.patch_tool import PatchTool
from tools.action_validator import ActionValidator


def test_patch_workflow():

    file = "workflow_test.py"


    with open(file, "w") as f:
        f.write('print("hello")')


    result = PatchTool.apply_patch(
        file,
        'print("hello")',
        'print("Hi")'
    )


    assert "Patched" in result


    validation = ActionValidator.validate_patch(
        file,
        'print("Hi")'
    )


    assert validation["success"] == True