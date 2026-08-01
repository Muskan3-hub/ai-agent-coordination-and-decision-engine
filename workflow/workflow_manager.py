from memory.shared_memory import SharedMemory


class WorkflowManager:

    def __init__(
        self,
        planner,
        coding,
        reviewer,
        documentation
    ):

        self.planner = planner
        self.coding = coding
        self.reviewer = reviewer
        self.documentation = documentation

        self.memory = SharedMemory()



    def execute(self, task, context=""):

        results = {}


        # -------------------------
        # 1. Planner Agent
        # -------------------------

        plan = self.planner.execute(
            task,
            context
        )

        self.memory.store(
            "planner_output",
            plan
        )

        results["planner"] = plan



        # -------------------------
        # 2. Coding Agent
        # -------------------------

        coding_input = f"""
User Task:

{task}


Implementation Plan:

{plan}
"""

        code = self.coding.solve_task(
            coding_input
        )

        self.memory.store(
            "coding_output",
            code
        )

        results["coding"] = code



        # -------------------------
        # 3. Reviewer Agent
        # -------------------------

        review = self.reviewer.review(
            code
        )

        self.memory.store(
            "review_output",
            review
        )

        results["review"] = review



        # -------------------------
        # 4. Documentation Agent
        # -------------------------

        documentation_input = f"""
Task:

{task}


Code:

{code}


Review:

{review}
"""

        docs = self.documentation.explain(
            documentation_input
        )

        self.memory.store(
            "documentation_output",
            docs
        )

        results["documentation"] = docs



        return results