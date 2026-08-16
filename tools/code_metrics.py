"""Enterprise code metrics (Task 9).

Deterministic static-analysis metrics computed from AST - no LLM calls:

    - cyclomatic complexity (per function + aggregate)
    - maintainability index (0-100)
    - documentation coverage (% of defs/classes with docstrings)
    - unused imports
    - unused variables
    - unreachable / dead code (statements after return/raise/break)
    - missing validation / exception-handling hints (LLM still narrates)
    - security score (0-100, heuristic)

All metrics are pure functions of the source text so they are trivially
testable and safe to run on untrusted input.
"""
import ast
import math
import re


def _parse(code):
    try:
        return ast.parse(code)
    except SyntaxError:
        return None


def cyclomatic_complexity(node):
    """McCabe complexity for a single function/class body."""
    complexity = 1
    for child in ast.walk(node):
        if isinstance(
            child,
            (ast.If, ast.While, ast.For, ast.Try, ast.ExceptHandler,
             ast.Assert, ast.BoolOp),
        ):
            complexity += 1
        elif isinstance(child, ast.Compare) and child.ops:
            complexity += 1
        elif isinstance(child, ast.AsyncFor):
            complexity += 1
    return complexity


def function_complexities(code):
    """Return [(name, complexity, lineno)] for every function."""
    tree = _parse(code)
    if tree is None:
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.name, cyclomatic_complexity(node), node.lineno))
    return out


def maintainability_index(code):
    """Microsoft-style MI (simplified, 0-100)."""
    tree = _parse(code)
    if tree is None:
        return 0.0
    functions = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if not functions:
        return 100.0
    avg_complexity = sum(cyclomatic_complexity(f) for f in functions) / len(functions)
    docstrings = sum(1 for f in functions if ast.get_docstring(f))
    doc_coverage = docstrings / len(functions)

    # Clamp inputs then combine into a 0-100 score.
    norm_complexity = max(0.0, min(10.0, avg_complexity))
    mi = 100 - (
        norm_complexity * 6.0          # complexity penalty
        + (1.0 - doc_coverage) * 20.0  # documentation penalty
    )
    return round(max(0.0, min(100.0, mi)), 1)


def documentation_coverage(code):
    """Return {total, documented, percent} for defs/classes."""
    tree = _parse(code)
    if tree is None:
        return {"total": 0, "documented": 0, "percent": 0.0}
    nodes = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    if not nodes:
        return {"total": 0, "documented": 0, "percent": 0.0}
    documented = sum(1 for n in nodes if ast.get_docstring(n))
    return {
        "total": len(nodes),
        "documented": documented,
        "percent": round(100 * documented / len(nodes), 1),
    }


def unused_imports(code):
    """Return a list of imported names never referenced in the body."""
    tree = _parse(code)
    if tree is None:
        return []
    imports = {}
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                imports[name] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                name = alias.asname or alias.name
                imports[name] = node.lineno
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
    return [name for name in imports if name not in used]


def unused_variables(code):
    """Simple heuristic: assigned-but-never-read local variables."""
    tree = _parse(code)
    if tree is None:
        return []
    reads = set()
    writes = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Store, ast.AugStore)):
                writes.setdefault(node.id, node.lineno)
            elif isinstance(node.ctx, ast.Load):
                reads.add(node.id)
    # Ignore dunder/underscore-prefixed names and imports.
    return [
        {"name": name, "line": lineno}
        for name, lineno in writes.items()
        if name not in reads
        and not name.startswith("_")
        and name not in {"self", "cls"}
    ]


def dead_code_regions(code):
    """Statements that can never run (after return/raise/break/continue)."""
    tree = _parse(code)
    if tree is None:
        return []
    dead = []

    def scan(body):
        for i, stmt in enumerate(body):
            if i == len(body) - 1:
                continue
            if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                dead.append({
                    "line": getattr(stmt, "lineno", 0),
                    "kind": type(stmt).__name__.lower(),
                })

    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if isinstance(body, list):
                scan(body)
    return dead


def security_score(code):
    """Heuristic 0-100: penalize dangerous patterns, reward hygiene."""
    tree = _parse(code)
    if tree is None:
        return 0
    score = 100
    source = code
    penalties = [
        (r"\beval\s*\(", 15, "eval()"),
        (r"\bexec\s*\(", 15, "exec()"),
        (r"pickle\.(loads|load)\s*\(", 12, "pickle deserialization"),
        (r"shell\s*=\s*True", 20, "shell=True"),
        (r"os\.system\s*\(", 12, "os.system()"),
        (r"subprocess\.(call|Popen)\s*\([^)]*shell\s*=\s*True", 15, "shell subprocess"),
        (r"sqlite3\.connect|execute\s*\(.*f[\"']", 8, "possible SQL injection"),
        (r"input\s*\([^)]*\)", 3, "unvalidated user input"),
    ]
    for pattern, penalty, label in penalties:
        if re.search(pattern, source):
            score -= penalty
    return max(0, min(100, score))


def class_count(code):
    """Number of class definitions (0 when code cannot be parsed)."""
    tree = _parse(code)
    if tree is None:
        return 0
    return sum(
        1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
    )


def import_count(code):
    """Number of import statements (0 when code cannot be parsed)."""
    tree = _parse(code)
    if tree is None:
        return 0
    return sum(
        1 for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
    )


def variable_count(code):
    """Number of assigned names at module level and in function bodies."""
    tree = _parse(code)
    if tree is None:
        return 0
    count = 0
    for n in ast.walk(tree):
        if not isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            continue
        targets = getattr(n, "targets", None) or [getattr(n, "target", None)]
        for t in targets:
            if isinstance(t, ast.Name) and not t.id.startswith("_"):
                count += 1
    return count


def analyze(code):
    """Run the full metrics suite and return a structured report."""
    tree = _parse(code)
    parse_ok = tree is not None
    complexities = function_complexities(code)
    max_complexity = max((c for _, c, _ in complexities), default=0)
    doc = documentation_coverage(code)
    sec = security_score(code)
    mi = maintainability_index(code)

    # Overall quality score: weighted blend.
    quality = round(
        0.45 * mi
        + 0.25 * sec
        + 0.20 * doc["percent"]
        + 0.10 * max(0, 100 - max_complexity * 8),
        1,
    )

    return {
        "parse_ok": parse_ok,
        "lines_of_code": len(code.splitlines()),
        "function_count": len(complexities),
        "class_count": class_count(code),
        "import_count": import_count(code),
        "variable_count": variable_count(code),
        "cyclomatic_complexity": {
            "average": round(
                (sum(c for _, c, _ in complexities) / len(complexities))
                if complexities else 0, 1
            ),
            "max": max_complexity,
            "per_function": [
                {"name": name, "complexity": comp, "line": line}
                for name, comp, line in complexities
            ],
        },
        "maintainability_index": mi,
        "documentation_coverage": doc,
        "unused_imports": unused_imports(code),
        "unused_variables": unused_variables(code),
        "dead_code_regions": dead_code_regions(code),
        "security_score": sec,
        "quality_score": quality,
    }
