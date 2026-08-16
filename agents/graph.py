"""LangGraph orchestration layer.

The coordinator's routing is re-expressed as a proper execution graph:

    START -> router (Decision Engine) -> specialized agent node -> END

Every specialized agent is a LangGraph node; the Decision Engine stays
the intent classifier (kept 1:1, nothing removed); the "Build
Application" flow is a 3-stage sub-graph (Planner -> Coding ->
Documentation) whose nodes share state - real multi-step execution and
agent collaboration.

Backward compatibility: nodes call the CoordinatorAgent's existing
handlers, so result dicts keep the exact same shape as before
(``{"response", "agent", ...}``).

Design notes (SOLID-ish):
- Graph structure lives here; agents stay unchanged.
- The workflow manager owns the per-stage logic; the graph drives it.
"""
import os
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

# ----------------------------------------------------------------------
# Shared state
# ----------------------------------------------------------------------


class WorkflowState(TypedDict, total=False):
    task: str
    context: str
    decision: str
    chain: str                # compound-workflow chain id (Milestone 4)
    response: str
    agent: str
    workflow: dict
    code: str
    planner: str
    coding: str
    documentation: str
    review: str               # Reviewer Agent output (project review chain)
    code_analysis: str        # Code Analysis output (explain chain)
    debug: str                # Debugging output (debug chain)
    project_report: str       # Project Analyzer report (review chain)
    progress: object          # optional fn(stage_index, total, name)
    memory_message: str       # short-memory entry for long responses


# ----------------------------------------------------------------------
# Workflow sub-graph (Planner -> Coding -> Documentation)
# ----------------------------------------------------------------------


def build_workflow_graph(coordinator):
    """3-stage Build-Application graph with shared state."""

    def wf_planner(state):
        progress = state.get("progress")
        if progress:
            progress(1, 3, "Planner Agent")
        plan = coordinator.workflow_manager.planner_stage(
            state["task"], state.get("context", "")
        )
        return {"planner": plan}

    def wf_coding(state):
        progress = state.get("progress")
        if progress:
            progress(2, 3, "Coding Agent")
        code = coordinator.workflow_manager.coding_stage(
            state["task"], state.get("planner", "")
        )
        return {"coding": coordinator.clean_code_output(code)}

    def wf_documentation(state):
        progress = state.get("progress")
        if progress:
            progress(3, 3, "Documentation Agent")
        docs = coordinator.workflow_manager.documentation_stage(
            state["task"], state.get("coding", "")
        )
        return {"documentation": docs}

    graph = StateGraph(WorkflowState)
    graph.add_node("wf_planner", wf_planner)
    graph.add_node("wf_coding", wf_coding)
    graph.add_node("wf_documentation", wf_documentation)
    graph.add_edge(START, "wf_planner")
    graph.add_edge("wf_planner", "wf_coding")
    graph.add_edge("wf_coding", "wf_documentation")
    graph.add_edge("wf_documentation", END)
    return graph.compile()


# ----------------------------------------------------------------------
# Intent-driven chain sub-graphs (Milestone 4 - complex orchestration)
# ----------------------------------------------------------------------
# Each chain is a small LangGraph StateGraph whose nodes share state, so
# every agent receives the previous agent's output through shared memory
# (the state object) instead of duplicated prompt text. Chains only run
# for explicit compound requests ("review the project", "debug this code
# and document the fix", "explain this code and generate documentation")
# - single-intent requests keep their existing one-agent routing.


def build_chain_graph(stages):
    """Build a sequential multi-agent chain graph.

    ``stages``: list of (node_name, fn) where fn(state) -> dict. Every
    node can read the shared state and write its own output back, so
    downstream agents see upstream results (shared state between agents).
    """
    graph = StateGraph(WorkflowState)
    for name, fn in stages:
        graph.add_node(name, fn)
    graph.add_edge(START, stages[0][0])
    for (a, _), (b, _) in zip(stages, stages[1:]):
        graph.add_edge(a, b)
    graph.add_edge(stages[-1][0], END)
    return graph.compile()


def _resolve_project_root(coordinator, state):
    """Root of the project under review: the CURRENT message's attached
    ZIP marker wins (the very first turn after an upload carries no
    active context yet - it is only stored after the graph completes),
    then the active project root. Returns None when there is no uploaded
    project - the workflow router answers with a friendly upload prompt
    instead of scanning the assistant's own workspace."""
    root = (
        coordinator._project_root(state["task"])
        or coordinator._active.get("project_root")
    )
    return root if root and os.path.isdir(root) else None


def build_review_project_graph(coordinator):
    """Review Project -> Project Analyzer -> Reviewer.

    The reviewer receives the analyzer's full report through the shared
    state (no re-prompting, no duplicated analysis).
    """

    def stage_analyzer(state):
        progress = state.get("progress")
        if progress:
            progress(1, 2, "Project Analyzer")
        # An uploaded ZIP project is the subject of the review - never
        # the app's own workspace.
        root = _resolve_project_root(coordinator, state)
        if not root:
            return {"project_report": coordinator.NO_PROJECT_MESSAGE}
        report = coordinator.project_analyzer.analyze_project(root)
        return {"project_report": report}

    def stage_reviewer(state):
        progress = state.get("progress")
        if progress:
            progress(2, 2, "Reviewer Agent")
        review = coordinator.reviewer.review(
            state.get("project_report", "")
        )
        return {"review": review}

    return build_chain_graph(
        [("project_analyzer", stage_analyzer), ("reviewer", stage_reviewer)]
    )


def build_review_project_fix_graph(coordinator):
    """Review Project -> Reviewer -> Coding (fix the findings).

    Handles "Review this project and fix the most important bug": the
    analyzer reports on the real project, the reviewer pinpoints the
    issues, and the coding stage returns corrected code for those
    issues - the full multi-agent pipeline the prompt example describes.
    """

    def stage_analyzer(state):
        progress = state.get("progress")
        if progress:
            progress(1, 3, "Project Analyzer")
        root = _resolve_project_root(coordinator, state)
        if not root:
            return {"project_report": coordinator.NO_PROJECT_MESSAGE,
                    "project_sources": ""}
        report = coordinator.project_analyzer.analyze_project(root)
        sources = coordinator._collect_project_sources(
            root, max_files=8, max_chars=15000
        )
        return {"project_report": report, "project_sources": sources or ""}

    def stage_reviewer(state):
        progress = state.get("progress")
        if progress:
            progress(2, 3, "Reviewer Agent")
        review = coordinator.reviewer.review(
            state.get("project_report", "")
        )
        return {"review": review}

    def stage_fix(state):
        progress = state.get("progress")
        if progress:
            progress(3, 3, "Coding Agent")
        fix_task = (
            "The reviewer found the issues below in the project sources. "
            "Fix the most important bug/issue and return only the complete "
            "corrected code for the affected file(s). Do not explain - "
            "output the corrected code only.\n\n"
            f"Project sources:\n\n{state.get('project_sources', '')}\n\n"
            f"Review findings:\n\n{state.get('review', '')}"
        )
        code = coordinator.clean_code_output(
            coordinator.coding.solve_task(fix_task)
        )
        return {"code": code}

    return build_chain_graph(
        [
            ("project_analyzer", stage_analyzer),
            ("reviewer", stage_reviewer),
            ("coding", stage_fix),
        ]
    )


def build_debug_chain_graph(coordinator):
    """Debug Code -> Debugger -> Documentation.

    The documentation stage receives the debugger's analysis so it can
    document the actual fix, not just the original request.
    """

    def stage_debug(state):
        progress = state.get("progress")
        if progress:
            progress(1, 2, "Debugging Agent")
        result = coordinator.debugging.debug_code(
            state["task"], state.get("context", "")
        )
        return {"debug": result}

    def stage_docs(state):
        progress = state.get("progress")
        if progress:
            progress(2, 2, "Documentation Agent")
        debug_out = state.get("debug", "")
        doc_task = (
            "Document the debugging session below: the reported problem, "
            "the root cause, the fix, and how to prevent it in the future.\n\n"
            f"Debugging session:\n\n{debug_out}"
        )
        docs = coordinator.docs.explain(doc_task, state.get("context", ""))
        return {"documentation": docs}

    return build_chain_graph(
        [("debugger", stage_debug), ("documenter", stage_docs)]
    )


def build_code_review_docs_graph(coordinator):
    """Write Code -> Code Analysis -> Reviewer -> Documentation.

    The generated code is shared through state, so analysis, review and
    documentation all act on the SAME code - the multi-agent pipeline
    keeps the code consistent from generation to final docs.
    """

    def stage_coding(state):
        progress = state.get("progress")
        if progress:
            progress(1, 4, "Coding Agent")
        result = coordinator._handle_coding(
            state["task"], state.get("context", ""), "coding"
        )
        return {"code": result.get("response", "")}

    def stage_analysis(state):
        progress = state.get("progress")
        if progress:
            progress(2, 4, "Code Analysis Agent")
        code = state.get("code") or state["task"]
        result = coordinator.code_analysis.analyze(code, state.get("context", ""))
        return {"code_analysis": result}

    def stage_reviewer(state):
        progress = state.get("progress")
        if progress:
            progress(3, 4, "Reviewer Agent")
        code = state.get("code") or state["task"]
        review = coordinator.reviewer.review(code)
        return {"review": review}

    def stage_docs(state):
        progress = state.get("progress")
        if progress:
            progress(4, 4, "Documentation Agent")
        doc_task = (
            "Write clear, complete documentation for the code below, "
            "covering purpose, structure and usage. Include anything "
            "from the review findings the user should know.\n\n"
            f"Code:\n\n{state.get('code', '')}\n\n"
            f"Analysis:\n\n{state.get('code_analysis', '')}"
        )
        docs = coordinator.docs.explain(doc_task, state.get("context", ""))
        return {"documentation": docs}

    return build_chain_graph(
        [
            ("coding", stage_coding),
            ("code_analysis", stage_analysis),
            ("reviewer", stage_reviewer),
            ("documentation", stage_docs),
        ]
    )


def build_explain_chain_graph(coordinator):
    """Explain Code -> Code Analysis -> Documentation.

    The documentation stage receives the analysis so it documents the
    code's actual structure and findings.
    """

    def stage_analysis(state):
        progress = state.get("progress")
        if progress:
            progress(1, 2, "Code Analysis Agent")
        code = coordinator._extract_code_for_analysis(
            state["task"], state.get("context", "")
        )
        if not code:
            code = state["task"]
        result = coordinator.code_analysis.analyze(code, state.get("context", ""))
        return {"code_analysis": result}

    def stage_docs(state):
        progress = state.get("progress")
        if progress:
            progress(2, 2, "Documentation Agent")
        analysis = state.get("code_analysis", "")
        doc_task = (
            "Write clear, complete documentation for the code analyzed "
            "below, covering its purpose, structure and key findings.\n\n"
            f"Analysis:\n\n{analysis}"
        )
        docs = coordinator.docs.explain(doc_task, state.get("context", ""))
        return {"documentation": docs}

    return build_chain_graph(
        [("code_analysis", stage_analysis), ("documenter", stage_docs)]
    )


# ----------------------------------------------------------------------
# Main graph
# ----------------------------------------------------------------------


def build_graph(coordinator):
    """Build the supervisor graph for a coordinator instance."""

    def router_node(state):
        # The coordinator may pre-compute the decision (follow-up explain
        # upgrade); otherwise classify here as before.
        decision = state.get("decision") or coordinator.decision_engine.decide(
            state["task"]
        )
        # Compound-workflow requests route to the workflow router, which
        # picks the matching multi-agent chain; everything else keeps its
        # existing single-agent routing (backward compatible).
        chain = coordinator.decision_engine.detect_chain(state["task"])
        # "Review the project" after BUILDING an application (generated
        # code in context, no uploaded ZIP) must review THAT code, not the
        # app's own workspace. Without an uploaded project root the
        # project-review chain would scan "." - downgrade to the plain
        # Reviewer Agent, which receives the generated code via the active
        # context. A real uploaded project (or no active code at all)
        # keeps the chain.
        if chain in ("review_project", "review_project_fix"):
            proot = (
                coordinator._project_root(state["task"])
                or coordinator._active.get("project_root")
            )
            has_generated = bool(
                coordinator._active.get("code")
                or coordinator._active.get("workflow")
            )
            if has_generated and not (proot and os.path.isdir(proot)):
                chain = None
        return {"decision": decision, "chain": chain}

    def route(state):
        if state.get("chain"):
            return "workflow_router"
        return state.get("decision") or "chat"

    # Each node wraps the existing coordinator handler and copies the
    # result fields into the shared state.
    def make_node(handler, name):
        def node(state):
            result = handler(state["task"])
            out = {"response": result.get("response", ""), "agent": result.get("agent", name)}
            if "workflow" in result:
                out["workflow"] = result["workflow"]
            if "code" in result:
                out["code"] = result["code"]
            return out

        return node

    def make_context_node(handler, name):
        """Node that passes the shared context (follow-up intelligence)
        to agents which accept it - debug, documentation, planner."""

        def node(state):
            result = handler(state["task"], state.get("context", ""))
            out = {"response": result.get("response", ""), "agent": result.get("agent", name)}
            if "workflow" in result:
                out["workflow"] = result["workflow"]
            if "code" in result:
                out["code"] = result["code"]
            return out

        return node

    def node_chat(state):
        # Go through the coordinator's chat handler (like every other
        # agent) so the turn is stored in short-term memory and the
        # summary/entity memory is updated - without this, follow-up
        # turns after a chat message see an empty conversation.
        result = coordinator._handle_chat(
            state["task"], state.get("context", "")
        )
        return {"response": result["response"], "agent": result["agent"]}

    def node_coding(state):
        # "execution" requests keep their execute-and-show behavior.
        decision = "execution" if state.get("decision") == "execution" else "coding"
        result = coordinator._handle_coding(
            state["task"], state.get("context", ""), decision
        )
        return {"response": result["response"], "agent": result["agent"]}

    def node_code_analysis(state):
        result = coordinator._handle_code_analysis(state["task"], state.get("context", ""))
        return {"response": result["response"], "agent": result["agent"]}

    def node_workflow(state):
        sub = coordinator._workflow_graph or build_workflow_graph(coordinator)
        coordinator._workflow_graph = sub
        out = sub.invoke(
            {
                "task": state["task"],
                "context": state.get("context", ""),
                "progress": state.get("progress"),
            }
        )
        wf = {
            "planner": out.get("planner", ""),
            "coding": out.get("coding", ""),
            "documentation": out.get("documentation", ""),
        }
        code = coordinator.clean_code_output(out.get("coding", ""))
        final_response = (
            "### \U0001f4cb Plan\n\n"
            f"{wf['planner']}\n\n"
            "### \U0001f4bb Code\n\n"
            f"```python\n{code}\n```\n\n"
            "### \U0001f4c4 Documentation\n\n"
            f"{wf['documentation']}"
        ).strip()
        # Keep the actual generated code in the short-term memory entry
        # (not just a one-line summary) so follow-ups like "review it" or
        # "analyze the above code" can find the code in context. The
        # summary line keeps it greppable; the fenced block is what the
        # code-analysis extractor reads. The code is capped so large apps
        # do not blow up the token budget of every later prompt.
        max_code_chars = 4000
        stored_code = code
        if len(stored_code) > max_code_chars:
            stored_code = stored_code[:max_code_chars].rstrip() + "\n# ... (truncated)"
        return {
            "response": final_response,
            "agent": "Collaborative Workflow",
            "workflow": wf,
            "code": code,
            "memory_message": (
                f"Collaborative workflow completed for: {state['task'][:200]}\n\n"
                f"```python\n{stored_code}\n```"
            ),
        }

    # Chain sub-graphs are cached on the coordinator so repeated chain
    # requests reuse the compiled graphs (no re-compilation per turn).
    def node_workflow_router(state):
        chain = state["chain"]
        # Safety: a review chain must never scan the assistant's own
        # workspace when no project was uploaded (and there is no
        # generated code to fall back on - that case is already downgraded
        # in the router node). Ask for the project files instead.
        if chain in ("review_project", "review_project_fix"):
            proot = (
                coordinator._project_root(state["task"])
                or coordinator._active.get("project_root")
            )
            if not (proot and os.path.isdir(proot)):
                agent_name = (
                    "Project Review Workflow" if chain == "review_project"
                    else "Project Review & Fix Workflow"
                )
                return {
                    "response": coordinator.NO_PROJECT_MESSAGE,
                    "agent": agent_name,
                }
        builders = {
            "review_project": build_review_project_graph,
            "review_project_fix": build_review_project_fix_graph,
            "debug_document": build_debug_chain_graph,
            "explain_document": build_explain_chain_graph,
            "code_review_docs": build_code_review_docs_graph,
        }
        build = builders.get(chain)
        if build is None:
            return {
                "response": f"Unknown workflow chain: {chain}",
                "agent": "Workflow Router",
            }
        cache = getattr(coordinator, "_chain_graphs", {})
        sub = cache.get(chain)
        if sub is None:
            sub = build(coordinator)
            cache[chain] = sub
            coordinator._chain_graphs = cache

        out = sub.invoke(
            {
                "task": state["task"],
                "context": state.get("context", ""),
                "progress": state.get("progress"),
            }
        )

        if chain == "review_project":
            report = out.get("project_report", "")
            review = out.get("review", "")
            wf = {"review": review}
            response = (
                "### \U0001f50d Project Analysis\n\n"
                f"{report}\n\n"
                "### \u2705 Reviewer Findings\n\n"
                f"{review}"
            ).strip()
            agent_name = "Project Review Workflow"
            memory_payload = f"{report}\n\n{review}"
        elif chain == "review_project_fix":
            report = out.get("project_report", "")
            review = out.get("review", "")
            code = out.get("code", "")
            wf = {"review": review, "code": code}
            response = (
                "### \U0001f50d Project Analysis\n\n"
                f"{report}\n\n"
                "### \u2705 Reviewer Findings\n\n"
                f"{review}\n\n"
                "### \U0001f4bb Corrected Code\n\n"
                f"```python\n{code}\n```"
            ).strip()
            agent_name = "Project Review & Fix Workflow"
            memory_payload = f"{report}\n\n{review}\n\n{code}"
        elif chain == "debug_document":
            debug = out.get("debug", "")
            docs = out.get("documentation", "")
            wf = {"debug": debug, "documentation": docs}
            response = (
                "### \U0001f41e Debugging\n\n"
                f"{debug}\n\n"
                "### \U0001f4c4 Documentation\n\n"
                f"{docs}"
            ).strip()
            agent_name = "Debug & Document Workflow"
            memory_payload = f"{debug}\n\n{docs}"
        elif chain == "code_review_docs":
            code = out.get("code", "")
            analysis = out.get("code_analysis", "")
            review = out.get("review", "")
            docs = out.get("documentation", "")
            wf = {
                "code": code,
                "code_analysis": analysis,
                "review": review,
                "documentation": docs,
            }
            response = (
                "### \U0001f4bb Generated Code\n\n"
                f"```python\n{code}\n```\n\n"
                "### \U0001f52c Code Analysis\n\n"
                f"{analysis}\n\n"
                "### \u2705 Reviewer Findings\n\n"
                f"{review}\n\n"
                "### \U0001f4c4 Documentation\n\n"
                f"{docs}"
            ).strip()
            agent_name = "Code Review & Docs Workflow"
            memory_payload = f"{code}\n\n{analysis}\n\n{review}\n\n{docs}"
        else:  # explain_document
            analysis = out.get("code_analysis", "")
            docs = out.get("documentation", "")
            wf = {"code_analysis": analysis, "documentation": docs}
            response = (
                "### \U0001f52c Code Analysis\n\n"
                f"{analysis}\n\n"
                "### \U0001f4c4 Documentation\n\n"
                f"{docs}"
            ).strip()
            agent_name = "Explain & Document Workflow"
            memory_payload = f"{analysis}\n\n{docs}"

        # Cap the memory entry so follow-up turns stay within budget.
        max_chars = 4000
        if len(memory_payload) > max_chars:
            memory_payload = memory_payload[:max_chars].rstrip() + "\n# ... (truncated)"
        return {
            "response": response,
            "agent": agent_name,
            "workflow": wf,
            "memory_message": (
                f"{agent_name} completed for: {state['task'][:200]}\n\n"
                f"{memory_payload}"
            ),
        }

    nodes = {
        "workflow_router": node_workflow_router,
        "memory_store": make_node(coordinator._handle_memory_store, "Memory Store"),
        "memory_recall": make_node(coordinator._handle_memory_recall, "Memory Recall"),
        "chat": node_chat,
        "workflow": node_workflow,
        "github": make_node(coordinator._handle_github, "GitHub Tool"),
        "project": make_context_node(
            lambda task, ctx: coordinator._handle_project(task, ctx),
            "Project Analyzer",
        ),
        "code_analysis": node_code_analysis,
        "review": make_context_node(
            lambda task, ctx: coordinator._handle_review(task, ctx),
            "Reviewer Agent",
        ),
        "debug": make_context_node(
            lambda task, ctx: coordinator._finish(
                task, coordinator.debugging.debug_code(task, ctx), "Debugging Agent"
            ),
            "Debugging Agent",
        ),
        "documentation": make_context_node(
            lambda task, ctx: coordinator._finish(
                task, coordinator.docs.explain(task, ctx), "Documentation Agent"
            ),
            "Documentation Agent",
        ),
        "planner": make_context_node(
            lambda task, ctx: coordinator._finish(
                task, coordinator.planner.execute(task, ctx), "Planner Agent"
            ),
            "Planner Agent",
        ),
        "patch": make_node(coordinator._handle_patch, "Patch Tool"),
        "file": make_node(coordinator._handle_file, "File Tool"),
        "coding": node_coding,
    }

    graph = StateGraph(WorkflowState)
    graph.add_node("router", router_node)
    for name, fn in nodes.items():
        graph.add_node(name, fn)

    graph.add_edge(START, "router")
    path_map = {name: name for name in nodes}
    # "execution" is a coding sub-flow (generate + run) handled by the
    # coding node; the node keeps the execution behaviour via state.
    path_map["execution"] = "coding"
    graph.add_conditional_edges(
        "router",
        route,
        path_map,  # every decision -> its agent node (or the chain router)
    )
    for name in nodes:
        graph.add_edge(name, END)
    return graph.compile()
