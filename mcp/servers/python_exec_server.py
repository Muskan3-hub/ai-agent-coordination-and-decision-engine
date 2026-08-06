"""Python Execution MCP server: sandboxed-ish code execution (Task 7).

Reuses the existing tools.code_executor (same restrictions) behind the
MCP contract so agents can run short snippets on demand.
"""
import io
import sys
import traceback

from mcp.base import MCPServer


class PythonExecMCPServer(MCPServer):
    name = "python_exec"

    actions = {
        "run": "Execute a Python snippet and return stdout/stderr",
    }

    def _action_run(self, params):
        code = params.get("code", "")
        if not code:
            return {"error": "code is required"}
        stdin_input = params.get("user_input", "")

        # Capture stdout/stderr.
        old_out, old_err = sys.stdout, sys.stderr
        buf = io.StringIO()
        sys.stdout = sys.stderr = buf
        try:
            # Provide a minimal input() for scripts expecting stdin.
            _input = input

            def patched_input(prompt=""):
                if prompt:
                    buf.write(prompt)
                return stdin_input

            builtins_input = __builtins__.input if hasattr(__builtins__, "input") else input
            try:
                builtins = __import__("builtins")
                builtins.input = patched_input
            except Exception:
                pass

            exec(compile(code, "<mcp_exec>", "exec"), {"__name__": "__main__"})
            success = True
            error = None
        except SystemExit:
            success = True
            error = None
        except Exception:
            success = False
            error = traceback.format_exc(limit=8)
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            try:
                builtins.input = builtins_input
            except Exception:
                pass

        result = {
            "success": success,
            "output": buf.getvalue(),
        }
        # Use a "traceback" key (not "error") so MCPManager does not
        # treat an in-script exception as an API-level failure - the
        # caller can still inspect success/traceback.
        if error is not None:
            result["traceback"] = error
        return result
