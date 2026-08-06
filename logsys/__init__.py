"""Enterprise logging: per-category rotating file logs with severity.

NOTE: named `logsys` (not `logging`) so it never shadows the stdlib
`logging` module.
"""
from logsys.enterprise_logger import get_logger, LogCategories

__all__ = ["get_logger", "LogCategories"]
