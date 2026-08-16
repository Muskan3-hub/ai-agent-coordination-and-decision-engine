"""Standalone REST API entrypoint (Milestone 4 - deployment).

Runs the API server on API_HOST / API_PORT (defaults 0.0.0.0:8787),
creating the default admin on first boot. Used by Docker, Render,
Railway and the Procfile so the API can run as its own process.

Usage:
    python scripts/start_api.py
"""

import os

from api import APIServer
from auth import AuthService
from database import get_db


def main():
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8787"))

    db = get_db()
    AuthService(db).ensure_default_admin()

    server = APIServer(host=host, port=port)
    server.serve()


if __name__ == "__main__":
    main()
