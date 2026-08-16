"""Enterprise logging.

Writes timestamped, severity-tagged entries to per-category log files
under logs/. The existing tools/logger.py ('assistant.log') remains
untouched for backward compatibility.

Categories: app, coordinator, agents, tools, errors, github, mcp,
            workflow, security.
"""
import logging
import os
import threading
from logging.handlers import RotatingFileHandler

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Level comes from the LOG_LEVEL env var (production deployment).
_LOG_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)

_FORMAT = "%(asctime)s | %(levelname)s | %(category)s | %(message)s"


class CategoryAdapter(logging.LoggerAdapter):
    """Attaches the category name to every record."""

    def process(self, msg, kwargs):
        kwargs["extra"] = {"category": self.extra["category"]}
        return msg, kwargs


class _CategoryLogger:
    """Small facade so callers write get_logger('agents').info(...)."""

    def __init__(self, logger, category):
        self._adapter = CategoryAdapter(logger, {"category": category})

    def _log(self, level, msg, *args, **kwargs):
        getattr(self._adapter, level)(msg, *args, **kwargs)

    def debug(self, msg, *a, **k): self._log("debug", msg, *a, **k)
    def info(self, msg, *a, **k): self._log("info", msg, *a, **k)
    def warning(self, msg, *a, **k): self._log("warning", msg, *a, **k)
    def error(self, msg, *a, **k): self._log("error", msg, *a, **k)
    def exception(self, msg, *a, **k): self._log("exception", msg, *a, **k)


# Log categories -> output file names.
LogCategories = {
    "app": "app.log",
    "coordinator": "coordinator.log",
    "agents": "agents.log",
    "tools": "tools.log",
    "errors": "errors.log",
    "github": "github.log",
    "mcp": "mcp.log",
    "workflow": "workflow.log",
    "security": "security.log",
}

_registry = {}
_registry_lock = threading.Lock()


def get_logger(category="app"):
    """Return a category-scoped logger (creates the file handler once)."""
    category = category if category in LogCategories else "app"
    with _registry_lock:
        if category in _registry:
            return _registry[category]

        filename = LogCategories[category]
        logger = logging.getLogger(f"enterprise.{category}")
        logger.setLevel(_LOG_LEVEL)
        logger.propagate = False

        handler = RotatingFileHandler(
            os.path.join(LOG_DIR, filename),
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)

        # Console handler so container platforms can collect logs.
        console = logging.StreamHandler()
        console.setLevel(_LOG_LEVEL)
        console.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(console)

        facade = _CategoryLogger(logger, category)
        _registry[category] = facade
        return facade
