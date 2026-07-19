from tools.file_tool import FileTool
from tools.code_executor import CodeExecutor
from tools.patch_tool import PatchTool
from tools.project_analyzer import ProjectAnalyzer
from tools.logger import logger
from tools.execution_tracker import ExecutionTracker


class ToolManager:


    def __init__(self):

        self.tools = {

            "file": FileTool(),

            "code_executor": CodeExecutor(),

            "patch": PatchTool(),

            "project_analyzer": ProjectAnalyzer()

        }



    def select_tool(self, task):

        task = task.lower()


        if any(word in task for word in [
            "run",
            "execute",
            "test",
            "python code"
        ]):

            return self.tools["code_executor"]



        elif any(word in task for word in [
            "modify",
            "change",
            "replace",
            "patch",
            "update file"
        ]):

            return self.tools["patch"]



        elif any(word in task for word in [
            "analyze",
            "structure",
            "project",
            "files"
        ]):

            return self.tools["project_analyzer"]



        elif any(word in task for word in [
            "read",
            "write",
            "delete",
            "file"
        ]):

            return self.tools["file"]



        return None
    def execute_tool(self, task, tool_input):

        try:

            tool = self.select_tool(task)

            if tool is None:

                logger.warning(f"No suitable tool found for task: {task}")

                return {
                    "success": False,
                    "tool": None,
                    "message": "No suitable tool found."
                }

            logger.info(
                f"Executing {tool.__class__.__name__} | Task: {task}"
            )

            result = tool.execute(tool_input)


            ExecutionTracker.log(
                tool.__class__.__name__,
                tool_input,
                "SUCCESS",
                result
            )


            logger.info(
                f"{tool.__class__.__name__} executed successfully."
            )


            return {
                "success": True,
                "tool": tool.__class__.__name__,
                "result": result
            }

        except Exception as e:

            ExecutionTracker.log(
                tool.__class__.__name__ if 'tool' in locals() else "Unknown",
                tool_input,
                "FAILED",
                str(e)
            )


            logger.error(
                f"Tool execution failed: {str(e)}"
            )

            return {
                "success": False,
                "tool": tool.__class__.__name__ if 'tool' in locals() else None,
                "message": str(e)
            }