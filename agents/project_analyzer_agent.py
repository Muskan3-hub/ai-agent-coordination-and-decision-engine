"""
Project Analyzer Agent (Task 3).

Combines static analysis (tools/project_analyzer.py) with LLM
interpretation to produce a complete project report:

- folder structure
- module dependency summary
- entry point detection
- technology stack
- python libraries used
- architecture overview
- potential issues
- improvement suggestions
- overall project health score (0-100)
"""

import json

from tools.project_analyzer import ProjectAnalyzer as ProjectAnalyzerTool
from prompts.project_analyzer_prompt import PROJECT_ANALYZER_PROMPT


class ProjectAnalyzer:

    def __init__(self, model, guard):
        self.model = model
        self.guard = guard
        self.tool = ProjectAnalyzerTool()

    def analyze_project(self, root="."):
        """Run static analysis + LLM report generation."""
        # 1) Static analysis (fast, no LLM)
        static = self.tool.analyze_project(root)

        # 2) Compute a deterministic health score
        static["health_score"] = self._compute_health_score(static)

        # 3) LLM narrative report on top of the static data
        if self.guard.can_call():
            self.guard.register_call()

            prompt = PROJECT_ANALYZER_PROMPT.format_messages(
                input=json.dumps(static, indent=2, default=str)
            )
            llm_report = self.model.ask(prompt)

            return (
                f"### 🏥 Overall Project Health Score: "
                f"{static['health_score']}/100\n\n"
                f"{llm_report}"
            )

        return (
            "LLM limit reached in ProjectAnalyzer - showing static summary:\n\n"
            + self._static_summary(static)
        )

    # ------------------------------------------------------------------
    # Health score
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_health_score(data):
        """
        Deterministic 0-100 health score based on static signals.
        The LLM later adds qualitative context around this number.
        """
        score = 20.0  # base

        # Structure / modularity
        file_count = data.get("file_count", 0)
        if file_count >= 10:
            score += 15
        elif file_count >= 3:
            score += 10
        elif file_count >= 1:
            score += 5

        # Entry point present
        if data.get("entry_points"):
            score += 15

        # Error handling
        try_blocks = data.get("try_except_blocks", 0)
        score += min(15, try_blocks * 2)

        # Documentation (docstrings)
        if file_count:
            doc_ratio = data.get("docstring_files", 0) / file_count
            score += doc_ratio * 15

        # Tests present
        if data.get("has_tests"):
            score += 10

        # Uses third-party libraries (healthier than reinventing)
        if data.get("libraries"):
            score += 5

        # Dependencies: files importing other modules indicates structure
        if len(data.get("module_dependencies", {})) >= 2:
            score += 5

        return int(min(100, max(0, round(score))))

    # ------------------------------------------------------------------
    # Fallback summary (when LLM unavailable)
    # ------------------------------------------------------------------
    @staticmethod
    def _static_summary(data):
        lines = [
            f"- 📁 Files: {data.get('file_count', 0)}",
            f"- 📝 Total lines: {data.get('total_lines', 0)}",
            f"- 🚀 Entry points: {', '.join(data.get('entry_points', [])) or 'none'}",
            f"- 🧩 Libraries: {', '.join(data.get('libraries', [])) or 'none'}",
            f"- ⚙️ Tech stack: {', '.join(data.get('tech_stack', [])) or 'Python'}",
            f"- 🐛 try/except blocks: {data.get('try_except_blocks', 0)}",
            f"- 🧪 Tests present: {'yes' if data.get('has_tests') else 'no'}",
            "",
            "Folder structure:",
        ]
        for path in data.get("structure", [])[:40]:
            lines.append(f"  - {path}")
        return "\n".join(lines)
