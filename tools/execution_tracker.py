import json
import os
import time

LOG_FILE = "memory/tool_execution_history.json"


class ExecutionTracker:

    @staticmethod
    def log(tool_name, input_data, status, result):

        # Internal monitoring (Milestone 4) - tool usage statistics.
        try:
            from monitoring.metrics import get_metrics
            get_metrics().record_tool(tool_name)
        except Exception:
            pass

        # -------------------------
        # Create concise summaries
        # -------------------------
        input_summary = {}

        if isinstance(input_data, dict):

            for key, value in input_data.items():

                if key == "code":
                    input_summary["code_length"] = len(value)

                elif key == "user_input":
                    input_summary["user_input"] = value

                else:
                    input_summary[key] = str(value)

        else:
            input_summary = str(input_data)

        result_summary = str(result)

        if len(result_summary) > 200:
            result_summary = result_summary[:200] + "..."

        record = {
            "tool": tool_name,
            "input": input_summary,
            "status": status,
            "result_summary": result_summary,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        os.makedirs("memory", exist_ok=True)

        history = []

        if os.path.exists(LOG_FILE):

            with open(LOG_FILE, "r", encoding="utf-8") as f:

                try:
                    history = json.load(f)

                except json.JSONDecodeError:
                    history = []

        history.append(record)

        with open(LOG_FILE, "w", encoding="utf-8") as f:

            json.dump(history, f, indent=4)

        # -------------------------
        # Mirror into the DB so the Analytics "Tool Usage" chart
        # and "Most used tool" highlight have data to render.
        # (Lazy import keeps this module decoupled from the DB.)
        # -------------------------
        try:
            from database import get_db
            db = get_db()
            db.log_tool(
                tool_name,
                action=None,
                status=status,
                detail=result_summary,
            )
        except Exception:
            # Logging must never break the tool call itself.
            pass

        return record