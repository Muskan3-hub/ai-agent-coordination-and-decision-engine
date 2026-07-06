from agents.coding_agent import CodingAgent
from agents.debugging_agent import DebuggingAgent
from agents.documentation_agent import DocumentationAgent
from agents.planner import Planner
from tools.logger import logger

from tools.project_analyzer import ProjectAnalyzer
from tools.code_executor import CodeExecutor
from tools.file_tool import FileTool
from tools.multi_file_parser import MultiFileParser
from tools.patch_parser import PatchParser
from tools.patch_tool import PatchTool
import time


class CoordinatorAgent:

    def __init__(self, model, guard, memory):

        # -------------------------
        # LLM Agents
        # -------------------------
        self.coding = CodingAgent(model, guard)
        self.debugging = DebuggingAgent(model, guard)
        self.docs = DocumentationAgent(model, guard)
        self.planner=Planner(model, guard)


        # -------------------------
        # Core Components
        # -------------------------
        self.model = model
        self.guard = guard
        self.memory= memory

        # -------------------------
        # Tools (Non-LLM)
        # -------------------------
        self.project_analyzer = ProjectAnalyzer()
        self.executor = CodeExecutor()

    def handle_task(self, task):

        task_lower = task.lower()
        start_time=time.time()
        logger.info(f"User Request:{task}")
        recent_context= self.memory.get_recent_context()

        # -------------------------
        # Keywords
        # -------------------------
        debug_keywords = [
            "debug",
            "fix",
            "bug",
            "error",
            "traceback"
        ]

        doc_keywords = [
            "explain",
            "what is",
            "how",
            "tutorial"
        ]

        project_keywords = [
            "analyze project",
            "project analysis",
            "explain project"
        ]

        execution_keywords = [
            "run",
            "execute",
            "output",
            "run this code"
        ]

        file_keywords = [
            "save file",
            "create file",
            "write file",
            "read file",
            "update file",
            "delete file"
        ]

        # Reset API guard
        self.guard.reset()

        response = ""
        agent_name = "Unknown"

        # =====================================================
        # 1. PROJECT ANALYSIS TOOL
        # =====================================================
        if any(k in task_lower for k in project_keywords):
            logger.info("Routing -> Project Analyzer")
            agent_name = "Project Analyzer"


            data = self.project_analyzer.analyze_project(".")

            structure = "\n".join(data["structure"])

            code_summary = ""

            for f in data["files"]:
                code_summary += (
                    f"\n\nFILE: {f['file']}\n"
                    f"{f['code'][:500]}\n"
                )

            prompt = f"""
Previous Conversation:
{recent_context}

You are a senior software engineer.

Analyze this Python project.

Explain:

1. Project purpose
2. Folder structure
3. Important files
4. Design quality
5. Possible improvements

Project Structure:
{structure}

Project Code:
{code_summary}

Current User Request:
{task}
"""


            response = self.coding.solve_task(prompt)

        # =====================================================
        # 2. DEBUGGING AGENT
        # =====================================================
        elif any(k in task_lower for k in debug_keywords):
            logger.info("Routing -> Debugging Agent")
            agent_name = "Debugging Agent"
            response = self.debugging.debug_code(task)
            

        # =====================================================
        # 3. DOCUMENTATION AGENT
        # =====================================================
        elif any(k in task_lower for k in doc_keywords):
            logger.info("Routing -> Documentation Agent")
            agent_name = "Documentation Agent"

            response = self.docs.explain(task)

        # =====================================================
       # =====================================================
        # 4. FILE TOOL
        # =====================================================
        elif any(k in task_lower for k in file_keywords):
            logger.info("Routing -> File Tool")
            agent_name = "File Tool"

            # -------------------------
            # READ FILE
            # -------------------------
            if "read file" in task_lower:

                filename = None

                for word in task.replace(",", " ").split():
                    if word.endswith(".py"):
                        filename = word
                        break

                if filename is None:
                    return{
                        "response":FileTool.read_file(filename),
                        "agent":agent_name
                    }

                if FileTool.exists(filename):
                    return {
                        "response":FileTool.read_file(filename),
                        "agent":agent_name
                    }
                       
                    

                return{
                    "response":"File not found.",
                    "agent":agent_name
                }

            # -------------------------
            # DELETE FILE
            # -------------------------
            if "delete file" in task_lower:

                filename = None

                for word in task.replace(",", " ").split():
                    if word.endswith(".py"):
                        filename = word
                        break

                if filename is None:
                    return{
                        "response":"No Python file specified.",
                        "agent":agent_name
                    }

                return{

                    "response":FileTool.delete_file(filename),
                    "agent":agent_name
                }
                        # -------------------------
            # UPDATE FILE
            # -------------------------
            if "update file" in task_lower:

                filename = None

                for word in task.replace(",", " ").split():
                    if word.endswith(".py"):
                        filename = word
                        break

                if filename is None:
                    return{
                        "response":"No Python file specified.",
                        "agent":agent_name
                    }
                if not FileTool.exists(filename):
                    return{
                        "response":"File not found.",
                        "agent":agent_name
                    }


                existing_code = FileTool.read_file(filename)

                prompt = f"""
Previous Conversation:
{recent_context}

Existing File:
{existing_code}

Update Request:
{task}

Return only the complete updated code.
"""

                response = self.coding.solve_task(prompt)

                code = response

                code = response.strip()

                if code.startswith("```python"):
                    code = code.replace("```python", "", 1).strip()

                elif code.startswith("```"):
                    code = code.replace("```", "", 1).strip()

                if code.endswith("```"):
                    code = code[:-3].strip()

                lines = code.splitlines()

                if lines and lines[0].strip().lower() == "python":
                    code = "\n".join(lines[1:])
                result = FileTool.write_file(filename, code)

                return {
                    "response":f"✅ {filename} updated successfully.",
                    "agent":agent_name
                }

            # -------------------------
            # CREATE / SAVE FILE
            # -------------------------
            prompt = f"""
Previous Conversation:
{recent_context}

Current User Request:
{task}
"""

            response = self.coding.solve_task(prompt)

            try:

                filename = "generated_code.py"

                words = task.replace(",", " ").split()

                for word in words:
                    if word.endswith(".py"):
                        filename = word
                        break

                code = response

                code = response.strip()

                if code.startswith("```python"):
                    code = code.replace("```python", "", 1).strip()

                elif code.startswith("```"):
                    code = code.replace("```", "", 1).strip()

                if code.endswith("```"):
                    code = code[:-3].strip()

                lines = code.splitlines()

                if lines and lines[0].strip().lower() == "python":
                    code = "\n".join(lines[1:])

                result = FileTool.write_file(filename, code)

                response += f"\n\n✅ {result}"

            except Exception as e:

                response += f"\n\n❌ File Saving Error: {e}"

        # =====================================================
        # 5. CODING AGENT (DEFAULT)
        # =====================================================
        else:
            logger.info("Routing -> Coding Agent")
            agent_name="Coding Agent"
            # -------------------------
            # PLANNING STEP
            # -------------------------
            plan = self.planner.execute(task, recent_context)

           
            prompt = f"""
You are an AI coding assistant.

You can either:

1. Generate full files in EXACTLY this format:

FILE: generated_program.py

print("Hello")

Rules:
- The FILE line must contain ONLY the filename.
- Start the Python code on the NEXT line.
- Never put Python code on the same line as FILE:.
- Do not use Markdown code fences.


Never overwrite:
- app.py
- main.py
- agents/coordinator.py

2. OR return PATCH updates in this format:

PATCH: app.py
REPLACE:
<old code>
WITH:
<new code>

Rules:
- Use FILE format for new files
- Use PATCH format for modifications
- Only output code, no explanation
- Return only raw Python code.
- Do NOT use Markdown.
- Do NOT use ```python or ``` fences.


Plan:
{plan}

Previous Conversation:
{recent_context}

User Request:
{task}
"""

            response = self.coding.solve_task(prompt)
           

            # -------------------------
            # PATCH SYSTEM (ADD HERE)
            # -------------------------
            if "PATCH:" in response:

                patches = PatchParser.parse(response)

                for p in patches:
                    result = PatchTool.apply_patch(
                        p["file"],
                        p["old"],
                        p["new"]
                    )

                    response += f"\n\n{result}"
            # -------------------------
            # MULTI FILE CHECK
            # -------------------------
            if "FILE:" in response:

                files = MultiFileParser.parse(response)

                protected_files = {
                    "app.py",
                    "main.py",
                    "agents/coordinator.py"
                }

                safe_files = []

                for file in files:
                    if file["path"] in protected_files:
                        continue
                    safe_files.append(file)

                saved = FileTool.write_multiple_files(safe_files)
                
                save_message = "\n".join(saved)

                
        # =====================================================
        # 6. CODE EXECUTION TOOL
        # =====================================================
        if any(k in task_lower for k in execution_keywords):
            agent_name = "Code Executor"

            try:
                code = response.strip()

                # Remove FILE: filename from the beginning
                if code.startswith("FILE:"):
                    first_newline = code.find("\n")

                    if first_newline != -1:
                        code = code[first_newline + 1:].strip()
                    else:
                        # FILE: and code are on the same line
                        parts = code.split(".py", 1)
                        if len(parts) == 2:
                            code = parts[1].strip()

                # Remove markdown fences
                if code.startswith("```python"):
                    code = code.replace("```python", "", 1).strip()
                elif code.startswith("```"):
                    code = code.replace("```", "", 1).strip()

                if code.endswith("```"):
                    code = code[:-3].strip()

                

                output = self.executor.execute(code)

                final_response = response

                if "save_message" in locals():
                    final_response += "\n\n" + save_message

                final_response += (
                        "\n\n"
                        "============\n"
                        "Execution Output\n"
                        "============\n"
                        f"{output}"
                    )

                response = final_response


            except Exception as e:

                response += f"\n\nExecution Error: {e}"
                logger.info("Request completed successfully.")
                execution_time=time.time() - start_time
                logger.info(f"Execution Time:{execution_time:2f}seconds")
        
        return {
            "response":response,
            "agent":agent_name
        }