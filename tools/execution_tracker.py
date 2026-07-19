import time
import json
import os


LOG_FILE = "memory/tool_execution_history.json"


class ExecutionTracker:

    @staticmethod
    def log(
        tool_name,
        input_data,
        status,
        result
    ):

        record = {
            "tool": tool_name,
            "input": input_data,
            "status": status,
            "result": result,
            "timestamp": time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        }


        os.makedirs(
            "memory",
            exist_ok=True
        )


        history = []

        if os.path.exists(LOG_FILE):

            with open(
                LOG_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                try:
                    history = json.load(f)

                except:
                    history = []


        history.append(record)


        with open(
            LOG_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                history,
                f,
                indent=4
            )


        return record