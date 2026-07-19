from tools.patch_tool import PatchTool

tool = PatchTool()

result = tool.execute({
    "file_path": "test.py",
    "old_code": 'print("hello")',
    "new_code": 'print("Hi")'
})

print(result)