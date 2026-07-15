from tools.file_tool import FileTool
from tools.code_executor import CodeExecutor
from tools.patch_tool import PatchTool
from tools.project_analyzer import ProjectAnalyzer



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