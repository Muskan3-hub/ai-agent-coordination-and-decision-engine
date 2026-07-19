from tools.tool_manager import ToolManager


manager = ToolManager()


result = manager.execute_tool(
    "github repository info",
    {
        "action":"repo_info",
        "owner":"openai",
        "repo":"openai-python"
    }
)


print(result)