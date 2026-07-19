class PatchParser:

    @staticmethod
    def parse(response: str):

        patches = []

        if "PATCH:" not in response:
            return patches

        blocks = response.split("PATCH:")

        for block in blocks[1:]:

            lines = block.strip().split("\n")

            if not lines:
                continue

            file_name = lines[0].strip()

            old_code = ""
            new_code = ""

            mode = None

            for line in lines[1:]:

                if "REPLACE:" in line:
                    mode = "old"
                    continue

                if "WITH:" in line:
                    mode = "new"
                    continue

                if mode == "old":
                    old_code += line + "\n"

                elif mode == "new":
                    new_code += line + "\n"


            # Remove extra spaces safely
            old_code = old_code.strip() if old_code else ""
            new_code = new_code.strip() if new_code else ""

            print("DEBUG PATCH DATA:")
            print("FILE:", file_name)
            print("OLD:", old_code)
            print("NEW:", new_code)


            patches.append({
                "file": file_name,
                "old": old_code,
                "new": new_code
            })


        return patches