from tools.file_tool import FileTool
from tools.patch_tool import PatchTool


def test_file_exists():

    assert FileTool.exists("app.py") == True



def test_patch_tool():

    with open("sample_test.py","w") as f:
        f.write('print("hello")')


    result = PatchTool.apply_patch(
        "sample_test.py",
        'print("hello")',
        'print("Hi")'
    )


    assert "Patched" in result


    with open("sample_test.py") as f:
        content = f.read()


    assert 'print("Hi")' in content