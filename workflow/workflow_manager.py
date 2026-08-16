from memory.shared_memory import SharedMemory


class WorkflowManager:
    """
    Collaborative multi-agent Build-Application workflow.

    Pipeline (upgraded):
        Planner -> Coding -> Documentation

    Every stage reads the outputs of the previous stages from Shared
    Memory, so each agent receives real context instead of duplicated
    prompt text. The per-stage methods are reused by the LangGraph flow
    (agents/graph.py), so the graph and the sequential ``execute()``
    path share exactly the same logic.
    """

    STAGES = [
        "Planner Agent",
        "Coding Agent",
        "Documentation Agent",
    ]

    def __init__(self, planner, coding, documentation):
        self.planner = planner
        self.coding = coding
        self.documentation = documentation

        self.memory = SharedMemory()

    # ------------------------------------------------------------------
    # Individual stages (shared with the LangGraph workflow sub-graph)
    # ------------------------------------------------------------------
    def planner_stage(self, task, context=""):
        plan = self.planner.execute(task, context)
        self.memory.store("planner_output", plan)
        return plan

    def coding_stage(self, task, plan=None):
        plan = plan or self.memory.get("planner_output") or ""
        coding_input = f"""
User Task:

{task}


Implementation Plan:

{plan}


Rules for the implementation:
- Implement EXACTLY what the plan describes; do not add features the
  plan does not mention (no "database" or "persistent storage" unless
  the plan actually specifies one - if the plan says in-memory, store
  data in Python dictionaries/lists and do NOT claim otherwise).
- Return complete, RUNNABLE code with every function defined and every
  import at the top of the file.
- Keep each method/function reasonably short; break repeated CRUD
  patterns into small helpers instead of duplicating them.
- Validate inputs where a wrong value would genuinely crash or corrupt
  the app; do not add validation for its own sake.

Return only the complete code for the application
(no markdown fences, no explanations).
"""
        code = self.coding.solve_task(coding_input)
        self.memory.store("coding_output", code)
        return code

    def documentation_stage(self, task, code=None):
        code = code or self.memory.get("coding_output") or ""
        documentation_input = f"""
Task:

{task}


Code:

{code}


Write clear, complete documentation for this application.
"""
        docs = self.documentation.explain(documentation_input)
        self.memory.store("documentation_output", docs)
        return docs

    # ------------------------------------------------------------------
    # Sequential pipeline (kept for non-graph callers)
    # ------------------------------------------------------------------
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

        # 1. Planner Agent
        notify(1, self.STAGES[0])
        results["planner"] = self.planner_stage(task, context)

        # 2. Coding Agent - reads planner output from Shared Memory
        notify(2, self.STAGES[1])
        results["coding"] = self.coding_stage(task, results["planner"])

        # 3. Documentation Agent - reads the code from Shared Memory
        notify(3, self.STAGES[2])
        results["documentation"] = self.documentation_stage(
            task, results["coding"]
        )

        return results
