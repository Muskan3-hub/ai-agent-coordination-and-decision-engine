import logging
import os
import sys

# Production logging (Milestone 4): level comes from the LOG_LEVEL env
# var (DEBUG|INFO|WARNING|ERROR) and records also go to stdout so
# container platforms (Docker, Render, Railway) can collect them.
_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
_level = getattr(logging, _log_level, logging.INFO)

logging.basicConfig(
    filename="assistant.log",
    level=_level,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("AI_Assistant")
logger.setLevel(_level)

# Mirror to stdout unless a handler already exists (idempotent).
if not any(isinstance(h, logging.StreamHandler) and h.stream is sys.stdout
           for h in logger.handlers):
    _console = logging.StreamHandler(sys.stdout)
    _console.setLevel(_level)
    _console.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(_console)