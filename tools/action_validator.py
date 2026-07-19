class ActionValidator:

    @staticmethod
    def validate_patch(file_path, new_code):

        try:

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            if new_code in content:
                return {
                    "success": True,
                    "message": "Patch verified successfully."
                }

            return {
                "success": False,
                "message": "Patch execution failed. New code not found."
            }

        except Exception as e:

            return {
                "success": False,
                "message": str(e)
            }