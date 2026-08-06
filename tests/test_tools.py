from tools.file_tool import FileTool
from tools.patch_tool import PatchTool
from tools.action_validator import ActionValidator


def test_file_exists():

    assert FileTool.exists("app.py") is True



def test_patch_tool(tmp_path):

    target = tmp_path / "sample_test.py"
    target.write_text('print("hello")', encoding="utf-8")

    result = PatchTool.apply_patch(
        str(target),
        'print("hello")',
        'print("Hi")'
    )

    assert "Patched" in result
    assert 'print("Hi")' in target.read_text(encoding="utf-8")


def test_patch_tool_validation(tmp_path):
    """Patch + ActionValidator flow (merged from the removed test_workflows.py)."""

    file = str(tmp_path / "workflow_test.py")
    with open(file, "w") as f:
        f.write('print("hello")')

    result = PatchTool.apply_patch(file, 'print("hello")', 'print("Hi")')
    assert "Patched" in result

    validation = ActionValidator.validate_patch(file, 'print("Hi")')
    assert validation["success"] is True