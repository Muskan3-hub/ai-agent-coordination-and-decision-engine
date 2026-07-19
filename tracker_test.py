from tools.execution_tracker import ExecutionTracker


ExecutionTracker.log(
    "PatchTool",
    {
        "file":"test.py"
    },
    "SUCCESS",
    "Patched successfully"
)


print("Tracker working")