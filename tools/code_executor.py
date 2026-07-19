from tools.base_tool import BaseTool
import subprocess
import tempfile
import os


class CodeExecutor(BaseTool):
    

    def execute(self, input_data):

        code = input_data.get("code")
        user_input = input_data.get("user_input", "")

        if code is None:
            return "No code provided"

        code = code.strip()

        if code.startswith("```python"):
            code = code.replace("```python", "", 1).strip()

        elif code.startswith("```"):
            code = code.replace("```", "", 1).strip()

        if code.endswith("```"):
            code = code[:-3].strip()

        lines = code.splitlines()

        if lines and lines[0].strip().lower() == "python":
            code = "\n".join(lines[1:])

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                delete=False
            ) as file:
                
                

                file.write(code)
                filename = file.name

            result = subprocess.run(
                ["python", filename],
                input=user_input,
                capture_output=True,
                text=True,
                timeout=10
            )
            os.remove(filename)

            if result.returncode == 0:
                return result.stdout

            return result.stderr

        except Exception as e:
            return str(e)