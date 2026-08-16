"""Response directive parsing (Milestone 5 - response quality control).

Detects explicit output-control requests embedded in a user message -
word count, difficulty level, coding style, complexity, output format
and code length - and turns them into a compact instruction block that
is appended to the agent prompt so the selected agent honors them.

The system never changes routing or architecture: directives only shape
HOW the chosen agent answers.
"""

import re

# ---------------------------------------------------------------------------
# Word count ("Explain AI in 50 words", "100-word summary", "in 5 lines")
# ---------------------------------------------------------------------------

_SPELLED_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
    "two hundred": 200, "five hundred": 500,
}

# "exactly 100 words" / "exactly 80 words" - a strict constraint the
# system must enforce programmatically (count, revise, verify) rather
# than treat as a loose "about N words".
_EXACT_WORD_PATTERN = re.compile(
    r"\bexactly\s+(?:only\s+)?(\d{1,4})\s+(?:words?|lines?)\b",
    re.IGNORECASE,
)


_WORD_COUNT_PATTERNS = [
    # "in 50 words", "in about 100 words", "within 200 words", "in 5 lines"
    re.compile(
        r"\b(?:in|within|under|around|about|using|with|write|in\s*just)\s+"
        r"(?:exactly|approximately|about|around|only|just|at\s*most|at\s*least)?\s*"
        r"(\d{1,4})\s+(?:words?|lines?)\b",
        re.IGNORECASE,
    ),
    # "exactly 50 words", "about 100 words"
    re.compile(
        r"\b(?:exactly|approximately|about|around|only|just|at\s*most|at\s*least)\s+"
        r"(\d{1,4})\s+(?:words?|lines?)\b",
        re.IGNORECASE,
    ),
    # "50-word summary", "200 word answer"
    re.compile(r"\b(\d{1,4})\s*-?\s*(?:word|line)\b", re.IGNORECASE),
    # spelled-out: "in five lines", "in ten lines"
    re.compile(
        r"\b(?:in|within|under|about|around|using|with)\s+"
        r"(?:exactly|approximately|about|around|only|just)?\s*"
        r"([a-z]+(?:\s+[a-z]+)?)\s+(?:words?|lines?)\b",
        re.IGNORECASE,
    ),
]


def _number_value(text):
    """Digits or spelled-out small numbers -> int, else None."""
    if text.isdigit():
        return int(text)
    return _SPELLED_NUMBERS.get(text.lower().strip())


def extract_word_count(task):
    for pattern in _WORD_COUNT_PATTERNS:
        m = pattern.search(task or "")
        if m:
            value = _number_value(m.group(1))
            if value:
                return value
    return None


def is_exact_word_count(task):
    """True when the user explicitly said "exactly N words/lines"."""
    return bool(_EXACT_WORD_PATTERN.search(task or ""))


# ---------------------------------------------------------------------------
# Difficulty level
# ---------------------------------------------------------------------------

_DIFFICULTY_PATTERNS = [
    # (regex, level)
    (
        re.compile(
            r"\b(simple words|simple language|simple terms|easy language|"
            r"easy words|simply|in plain english|layman|basic terms)\b",
            re.IGNORECASE,
        ),
        "simple",
    ),
    (
        re.compile(
            r"\b(for beginners|beginner-friendly|beginner friendly|beginner level|"
            r"new to|absolute beginner|dummies)\b",
            re.IGNORECASE,
        ),
        "beginner",
    ),
    (
        re.compile(
            r"\b(for a 10[- ]year[- ]old|for kids|for children|for a child|"
            r"for a 5th grader|for a 6th grader|in simple english|like i'm 5)\b",
            re.IGNORECASE,
        ),
        "beginner",
    ),
    (
        re.compile(
            r"\b(technical terms|in technical|with jargon|for experts|advanced terms|"
            r"in depth|in-depth|deep dive|in detail|comprehensive|thoroughly)\b",
            re.IGNORECASE,
        ),
        "detailed",
    ),
    (
        re.compile(
            r"\b(interview style|interview answer|for an interview|for interviews|"
            r"interview question)\b",
            re.IGNORECASE,
        ),
        "interview",
    ),
    (
        re.compile(
            r"\b(academic style|academic|scholarly|research style|formal style)\b",
            re.IGNORECASE,
        ),
        "academic",
    ),
    (
        re.compile(
            r"\b(briefly|in brief|in short|concise explanation|short answer|"
            r"quick summary|summarize)\b",
            re.IGNORECASE,
        ),
        "brief",
    ),
]

_DIFFICULTY_HINTS = {
    "simple": "plain, everyday language with short sentences; avoid jargon",
    "beginner": "extremely simple language suitable for a beginner or a child; "
                "use analogies and define every term",
    "detailed": "technical depth, precise terminology and thorough coverage",
    "interview": "structure it like a strong interview answer: definition, "
                 "key points, example, and a crisp takeaway",
    "academic": "formal, precise academic tone with structured reasoning",
    "brief": "short and to the point; omit examples unless asked",
}


# ---------------------------------------------------------------------------
# Coding style
# ---------------------------------------------------------------------------

_STYLE_PATTERNS = [
    (re.compile(r"\b(object[- ]oriented|oop|classes? and objects|class-based)\b", re.IGNORECASE), "oop"),
    (re.compile(r"\b(using functions|function[- ]based|with functions|functional style)\b", re.IGNORECASE), "functional"),
    (re.compile(r"\b(production[- ]ready|production grade|production quality|enterprise[- ]grade|"
                r"professional(?: code)?|industry[- ]standard)\b", re.IGNORECASE), "production"),
    (re.compile(r"\b(optimized|optimised|efficient|performance[- ]focused|high[- ]performance)\b", re.IGNORECASE), "optimized"),
    (re.compile(r"\b(clean code|best practices|well[- ]structured|well[- ]written)\b", re.IGNORECASE), "clean"),
    (re.compile(r"\b(simple (?:python|java|javascript|code)|easy (?:python|java|javascript|code)|"
                r"beginner[- ]friendly code|beginner[- ]level (?:python|java|javascript|code))\b",
                re.IGNORECASE), "simple"),
]

_STYLE_HINTS = {
    "oop": "use classes and objects; encapsulate behavior in well-named classes",
    "functional": "implement the logic as clean, reusable functions",
    "production": "modular, clean, scalable code with error handling and "
                  "industry best practices",
    "optimized": "write time- and space-efficient code; explain the complexity",
    "clean": "readable code following best practices with clear naming",
    "simple": "beginner-friendly, minimal syntax with obvious variable names",
}


# ---------------------------------------------------------------------------
# Code complexity / length
# ---------------------------------------------------------------------------

_COMPLEXITY_PATTERNS = [
    (re.compile(r"\b(advanced (?:implementation|solution|code)|expert[- ]level)\b", re.IGNORECASE), "advanced"),
    (re.compile(r"\b(production[- ]ready|optimized|efficient)\s+(?:implementation|solution)\b", re.IGNORECASE), "optimized"),
    (re.compile(r"\b(basic (?:implementation|solution)|simple (?:implementation|solution)|beginner (?:implementation|solution))\b", re.IGNORECASE), "basic"),
]

_COMPLEXITY_HINTS = {
    "basic": "keep it simple: minimal features, clear and easy to follow",
    "advanced": "implement full features with edge cases, error handling and "
                "robustness",
    "optimized": "prioritize time/space efficiency and scalability",
}

_LENGTH_PATTERNS = [
    (re.compile(r"\b(short code|concise implementation|minimum lines|compact(?: code)?|"
                r"as short as possible|minimal code)\b", re.IGNORECASE), "short"),
    (re.compile(r"\b(fully commented|well[- ]commented|detailed implementation|"
                r"complete implementation|thorough|full solution)\b", re.IGNORECASE), "detailed"),
]

_LENGTH_HINTS = {
    "short": "keep the code as compact as possible while remaining correct",
    "detailed": "provide a complete, structured solution with comments explaining "
                "each part",
}


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------

_FORMAT_PATTERNS = [
    (re.compile(r"\b(only code|code only|just the code|code without explanation|"
                r"no explanation|without explanation|only the code|only provide code|"
                r"provide only code|only the (?:corrected|fixed|optimized|optimised|"
                r"final|complete|updated) code)\b",
                re.IGNORECASE), "code_only"),
    (re.compile(r"\b(explanation only|no code|don'?t write code|without code|"
                r"only provide explanation|provide only explanation|only explanation)\b",
                re.IGNORECASE), "explanation_only"),
    (re.compile(r"\b(only algorithm|algorithm only|give only algorithm)\b", re.IGNORECASE), "pseudocode"),
    (re.compile(r"\b(step by step|step-by-step|numbered steps|stepwise)\b", re.IGNORECASE), "steps"),
    (re.compile(r"\b(pseudo code|pseudocode|algorithm format|as an algorithm)\b", re.IGNORECASE), "pseudocode"),
    (re.compile(r"\b(flowchart(?: explanation)?|flow diagram)\b", re.IGNORECASE), "flowchart"),
    (re.compile(r"\b(bullet points?|bulleted|as bullets)\b", re.IGNORECASE), "bullets"),
    (re.compile(r"\b(table format|in a table|tabular form|as a table)\b", re.IGNORECASE), "table"),
    (re.compile(r"\b(as a list|numbered list|list format)\b", re.IGNORECASE), "list"),
]

_FORMAT_HINTS = {
    "code_only": "output ONLY the code - no explanations, no markdown prose",
    "explanation_only": "explain without writing code",
    "steps": "present it as a step-by-step numbered sequence",
    "pseudocode": "present it as pseudocode / an algorithm outline",
    "flowchart": "describe the flow step by step, in flowchart order",
    "bullets": "use concise bullet points",
    "table": "organize the answer in a table",
    "list": "use a numbered list",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_directives(task):
    """Return a dict of response directives detected in ``task``.

    Only fields that were explicitly requested are present, so a plain
    request produces ``{}`` and is answered exactly as before.
    """
    d = {}
    wc = extract_word_count(task)
    if wc:
        d["word_count"] = wc
        if is_exact_word_count(task):
            d["word_count_exact"] = True

    for pattern, level in _DIFFICULTY_PATTERNS:
        if pattern.search(task or ""):
            d["difficulty"] = level
            break

    for pattern, style in _STYLE_PATTERNS:
        if pattern.search(task or ""):
            d["code_style"] = style
            break

    for pattern, level in _COMPLEXITY_PATTERNS:
        if pattern.search(task or ""):
            d["complexity"] = level
            break

    for pattern, mode in _LENGTH_PATTERNS:
        if pattern.search(task or ""):
            d["length"] = mode
            break

    for pattern, fmt in _FORMAT_PATTERNS:
        if pattern.search(task or ""):
            d["format"] = fmt
            break

    return d


def directives_block(directives):
    """Build a compact instruction block the generating agent must follow."""
    if not directives:
        return None
    lines = ["[Response requirements]"]
    if directives.get("word_count"):
        if directives.get("word_count_exact"):
            lines.append(
                f"- Length: EXACTLY {directives['word_count']} words. "
                "Count your words before replying and adjust until the "
                "count matches exactly; never exceed or fall short."
            )
        else:
            lines.append(
                f"- Length: approximately {directives['word_count']} words "
                "(plus or minus 5 words)."
            )
    if directives.get("difficulty"):
        lines.append(
            f"- Tone/difficulty: {_DIFFICULTY_HINTS[directives['difficulty']]}."
        )
    if directives.get("code_style"):
        lines.append(
            f"- Code style: {_STYLE_HINTS[directives['code_style']]}."
        )
    if directives.get("complexity"):
        lines.append(
            f"- Complexity: {_COMPLEXITY_HINTS[directives['complexity']]}."
        )
    if directives.get("length"):
        lines.append(
            f"- Code size: {_LENGTH_HINTS[directives['length']]}."
        )
    if directives.get("format"):
        lines.append(
            f"- Output format: {_FORMAT_HINTS[directives['format']]}."
        )
    lines.append("Follow these requirements strictly; do not add extra sections.")
    return "\n".join(lines)
