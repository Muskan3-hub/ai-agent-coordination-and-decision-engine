from memory.shared_memory import SharedMemory


class WorkflowManager:
    """
    Collaborative multi-agent workflow.

    Pipeline (Task 7):
        Planner -> Coding -> Reviewer -> Code Analysis -> Documentation

    Every stage reads the outputs of the previous stages from Shared
    Memory, so each agent receives real context instead of duplicated
    prompt text.
    """

    STAGES = [
        "Planner Agent",
        "Coding Agent",
        "Reviewer Agent",
        "Code Analysis Agent",
        "Documentation Agent",
    ]

    def __init__(
        self,
        planner,
        coding,
        reviewer,
        code_analysis,
        documentation,
    ):
        self.planner = planner
        self.coding = coding
        self.reviewer = reviewer
        self.code_analysis = code_analysis
        self.documentation = documentation

        self.memory = SharedMemory()

    def execute(self, task, context="", progress_callback=None):
        """
        Run the full pipeline.

        Args:
            task: the user request
            context: previous conversation context
            progress_callback: optional fn(stage_index, total, stage_name)
                               invoked before each stage so the UI can
                               render live progress.
        """
        total = len(self.STAGES)
        results = {}

        def notify(index, name):
            if progress_callback is not None:
                progress_callback(index, total, name)

        # -------------------------
        # 1. Planner Agent
        # -------------------------
        notify(1, self.STAGES[0])
        plan = self.planner.execute(task, context)
        self.memory.store("planner_output", plan)
        results["planner"] = plan

        # -------------------------
        # 2. Coding Agent - reads planner output from Shared Memory
        # -------------------------
        notify(2, self.STAGES[1])
        plan_from_memory = self.memory.get("planner_output") or plan

        coding_input = f"""
User Task:

{task}


Implementation Plan:

{plan_from_memory}
"""

        code = self.coding.solve_task(coding_input)
        self.memory.store("coding_output", code)
        results["coding"] = code

        # -------------------------
        # 3. Reviewer Agent - reviews coding output from Shared Memory
        # -------------------------
        notify(3, self.STAGES[2])
        code_from_memory = self.memory.get("coding_output") or code

        review = self.reviewer.review(code_from_memory)
        self.memory.store("review_output", review)
        results["review"] = review

        # -------------------------
        # 4. Code Analysis Agent - analyzes code from Shared Memory
        # -------------------------
        notify(4, self.STAGES[3])
        code_for_analysis = self.memory.get("coding_output") or code

        analysis = self.code_analysis.analyze(code_for_analysis)
        self.memory.store("code_analysis_output", analysis)
        results["code_analysis"] = analysis

        # -------------------------
        # 5. Documentation Agent - reads code + review + analysis
        # -------------------------
        notify(5, self.STAGES[4])
        code_for_docs = self.memory.get("coding_output") or code
        review_for_docs = self.memory.get("review_output") or review
        analysis_for_docs = self.memory.get("code_analysis_output") or analysis

        documentation_input = f"""
Task:

{task}


Code:

{code_for_docs}


Review:

{review_for_docs}


Code Analysis:

{analysis_for_docs}
"""

        docs = self.documentation.explain(documentation_input)
        self.memory.store("documentation_output", docs)
        results["documentation"] = docs

        return results
