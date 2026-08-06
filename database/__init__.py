"""Enterprise database layer (SQLite by default, PostgreSQL-ready)."""
from database.db import Database, get_db, init_db

__all__ = ["Database", "get_db", "init_db"]
