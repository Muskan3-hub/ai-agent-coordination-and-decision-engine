class MultiFileParser:

    @staticmethod
    def parse(response: str):
        """
        Converts LLM response into structured files
        """

        files = []
        current_file = None
        current_code = []

        lines = response.split("\n")

        for line in lines:

            if line.startswith("FILE:"):
                if current_file:
                    files.append({
                        "path": current_file,
                        "content": "\n".join(current_code)
                    })

                current_file = line.replace("FILE:", "").strip()
                current_code = []

            else:
                current_code.append(line)

        if current_file:
            files.append({
                "path": current_file,
                "content": "\n".join(current_code)
            })

        return files