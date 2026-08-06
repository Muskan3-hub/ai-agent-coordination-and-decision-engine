"""
Code Analysis Agent (Task 1) + Enterprise metrics (Task 9).

A specialized agent that ANALYZES code only - it never generates or
modifies code. It combines:
    - deterministic static metrics (tools.code_metrics: cyclomatic
      complexity, maintainability index, doc coverage, unused imports,
      unused variables, dead code, security score)
    - an LLM narrative report (bugs, smells, validations, suggestions)

The metrics are always included, so even when the LLM limit is reached
the user still receives a valuable, structured analysis.
"""

from prompts.code_analysis_prompt import CODE_ANALYSIS_PROMPT
from tools.code_metrics import analyze as compute_metrics


class CodeAnalysisAgent:

    def __init__(self, model, guard):
        self.model = model
        self.guard = guard

    def analyze(self, code, context=""):
        """Analyze the provided code and return a detailed report.

        Args:
            code: the source code to analyze
            context: optional previous-conversation context
        """
        metrics = compute_metrics(code)
        metrics_block = self._format_metrics(metrics)

        task = f"Code to analyze:\n\n{code}"
        if context:
            task = f"Previous Conversation:\n{context}\n\n{task}"

        if not self.guard.can_call():
            return self._metrics_only_report(metrics, metrics_block)

        self.guard.register_call()

        prompt = CODE_ANALYSIS_PROMPT.format_messages(
            input=f"{metrics_block}\n\n{task}"
        )
        llm_report = self.model.ask(prompt)

        return (
            f"{metrics_block}\n\n"
            "---\n\n"
            "## 🔍 Detailed Analysis (LLM)\n\n"
            f"{llm_report}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _format_metrics(m):
        cc = m["cyclomatic_complexity"]
        dc = m["documentation_coverage"]

        def bullet_list(items, default="None detected"):
            items = list(items)  # accept generators too
            if not items:
                return f"- {default}"
            return "\n".join(f"- {i}" for i in items[:12])

        def dead_lines(regions):
            if not regions:
                return "None detected"
            return "; ".join(
                "line {} ({})".format(r['line'], r['kind']) for r in regions[:12]
            )

        unused_vars = bullet_list(
            "{} (line {})".format(v['name'], v['line'])
            for v in m['unused_variables']
        )
        complex_fns = bullet_list(
            "{} (complexity {}, line {})".format(
                p['name'], p['complexity'], p['line']
            )
            for p in sorted(
                cc['per_function'], key=lambda x: -x['complexity']
            )[:5]
        )

        return (
            "## 📊 Static Metrics (deterministic)\n\n"
            f"- **Overall quality score:** {m['quality_score']}/100\n"
            f"- **Maintainability Index:** {m['maintainability_index']}/100\n"
            f"- **Security score:** {m['security_score']}/100\n"
            f"- **Lines of code:** {m['lines_of_code']}  |  "
            f"**Functions:** {m['function_count']}\n"
            f"- **Cyclomatic complexity:** avg {cc['average']}, "
            f"max {cc['max']}\n"
            f"- **Documentation coverage:** {dc['percent']}% "
            f"({dc['documented']}/{dc['total']} documented)\n\n"
            f"**Unused imports:**\n{bullet_list(m['unused_imports'])}\n\n"
            f"**Unused variables:**\n{unused_vars}\n\n"
            f"**Dead code regions:**\n{dead_lines(m['dead_code_regions'])}\n\n"
            f"**High-complexity functions:**\n{complex_fns}"
        )

    def _metrics_only_report(self, metrics, block):
        return (
            f"{block}\n\n---\n\n"
            "⚠️ LLM analysis skipped (call limit reached) - "
            "the static metrics above are still authoritative."
        )
