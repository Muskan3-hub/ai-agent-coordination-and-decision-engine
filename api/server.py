"""REST API server (Task 17).

A dependency-free JSON API built on the stdlib http.server so it runs
anywhere. Endpoints mirror the coordinator's routing:

    POST /api/login          {"username","password"} -> token
    POST /api/chat           {"message","token"}     -> routed response
    POST /api/code           {"message","token"}     -> coding
    POST /api/debug          {"message","token"}     -> debugging
    POST /api/analyze        {"code"}                -> code analysis
    POST /api/project        {"token"}               -> project analysis
    POST /api/github         {"owner","repo","action","token"}
    POST /api/workflow       {"message","token"}     -> workflow
    POST /api/workflows/execute {"message","type","token"} -> chain workflow
    GET  /api/workflows/{id} {"token"}               -> workflow status
    GET  /api/workflows      {"token"}               -> workflow history
    GET  /api/agents/logs    {"token"}               -> agent execution logs
    GET  /api/system/health                          -> health + metrics
    GET  /api/dashboard      {"token"}               -> stats
    GET  /api/health                                 -> liveness

All endpoints return JSON: {"success": bool, ...}.

Monitoring (Milestone 4): every request is timed and recorded in the
internal ``monitoring.metrics`` module (never rendered in the UI);
workflow execution, agent latency and tool/LLM usage are tracked there
and exposed only via /api/system/health.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from auth import AuthService
from database import get_db
from models.llm import LLM
from tools.llm_guard import LLMGuard
from memory.memory import Memory
from memory.short_term_memory import ShortTermMemory
from agents.coordinator import CoordinatorAgent
from monitoring.metrics import get_metrics

# Workflow "type" -> directive that triggers the matching chain in the
# Decision Engine / graph (Milestone 4 complex orchestration). With
# type="auto" (or omitted) the message itself is routed naturally.
WORKFLOW_DIRECTIVES = {
    "build": "Build an application: {}",
    "review_project": "Review this project: {}",
    "debug_document": "Debug this code and document the fix: {}",
    "explain_document": "Explain this code and generate documentation: {}",
}


class APIServer:
    """Thin wrapper that wires the Coordinator to a ThreadingHTTPServer."""

    def __init__(self, host="127.0.0.1", port=8787, coordinator=None):
        self.host = host
        self.port = port
        self.db = get_db()
        self.auth = AuthService(self.db)
        # Lazy coordinator so /health works even before the LLM is ready.
        self._coordinator = coordinator
        self._coord_lock = threading.Lock()
        self._httpd = None

    # ------------------------------------------------------------------
    def get_coordinator(self):
        if self._coordinator is None:
            with self._coord_lock:
                if self._coordinator is None:
                    model = LLM()
                    guard = LLMGuard()
                    memory = Memory()
                    short_memory = ShortTermMemory()
                    self._coordinator = CoordinatorAgent(
                        model, guard, memory, short_memory
                    )
        return self._coordinator

    def _handle_request(self, method, path, body):
        """Route a single HTTP request. Returns (status_code, payload_dict)."""

        # ---------------- Auth ----------------
        if method == "POST" and path == "/api/login":
            username = body.get("username", "")
            password = body.get("password", "")
            user, token = self.auth.login(username, password)
            if not token:
                return 401, {"success": False, "error": "Invalid credentials"}
            return 200, {"success": True, "token": token, "user": user["username"], "role": user["role"]}

        # ---------------- Health / dashboard / monitoring ----------------
        if method == "GET" and path == "/api/health":
            return 200, {"success": True, "status": "ok", "time": time.time()}

        if method == "GET" and path == "/api/system/health":
            """Deep health: process metrics, memory, DB liveness, workflow
            completion - internal monitoring, never shown in the UI."""
            return 200, {
                "success": True,
                "status": "ok",
                "time": time.time(),
                "metrics": get_metrics().snapshot(),
                "database": self._db_health(),
                "workflows": {
                    "total": self.db.count_workflows(),
                    "by_status": self._workflow_status_counts(),
                },
            }

        if method == "GET" and path == "/api/dashboard":
            user = self.auth.get_session_user(body.get("token", ""))
            if not user:
                return 401, {"success": False, "error": "Unauthorized"}
            return 200, {"success": True, "data": self.db.dashboard_stats()}

        # ---------------- Workflow APIs (Milestone 4) ----------------
        if method == "POST" and path == "/api/workflows/execute":
            user = self.auth.get_session_user(body.get("token", ""))
            if not user:
                return 401, {"success": False, "error": "Unauthorized"}
            message = body.get("message", "")
            if not message:
                return 400, {"success": False, "error": "message is required"}
            wf_type = body.get("type", "auto")
            task_message = self._workflow_directive(wf_type, message)
            coordinator = self.get_coordinator()
            start = time.time()
            try:
                result = coordinator.handle_task(task_message)
                duration_ms = int((time.time() - start) * 1000)
                agent = result.get("agent", "Workflow")
                wf_id = None
                if "workflow" in result:
                    self.db.save_workflow(
                        user["id"], message[:500], result["workflow"], "completed"
                    )
                    rows = self.db.list_workflows(user["id"], limit=1)
                    wf_id = rows[0]["id"] if rows else None
                self.db.log_execution(user["id"], agent, "success", duration_ms)
                get_metrics().record_agent(agent, duration_ms)
                get_metrics().record_workflow(ok=True)
            except Exception as exc:
                duration_ms = int((time.time() - start) * 1000)
                self.db.log_execution(user["id"], "workflow", "error", duration_ms)
                get_metrics().record_workflow(ok=False)
                return 500, {"success": False, "error": str(exc)}
            return 200, {
                "success": True,
                "workflow_id": wf_id,
                "status": "completed",
                "agent": agent,
                "response": result.get("response"),
            }

        if method == "GET" and path == "/api/workflows":
            user = self.auth.get_session_user(body.get("token", ""))
            if not user:
                return 401, {"success": False, "error": "Unauthorized"}
            return 200, {
                "success": True,
                "workflows": self.db.list_workflows(user["id"], limit=50),
            }

        if method == "GET" and path.startswith("/api/workflows/"):
            user = self.auth.get_session_user(body.get("token", ""))
            if not user:
                return 401, {"success": False, "error": "Unauthorized"}
            try:
                wf_id = int(path.rsplit("/", 1)[1])
            except ValueError:
                return 400, {"success": False, "error": "invalid workflow id"}
            row = self.db.get_workflow(wf_id)
            if not row:
                return 404, {"success": False, "error": "workflow not found"}
            return 200, {"success": True, "workflow": row}

        if method == "GET" and path == "/api/agents/logs":
            user = self.auth.get_session_user(body.get("token", ""))
            if not user:
                return 401, {"success": False, "error": "Unauthorized"}
            return 200, {
                "success": True,
                "logs": self.db.list_agent_logs(50),
                "executions": self.db.list_executions(user["id"], limit=50),
            }

        # ---------------- Coordinator-driven endpoints ----------------
        if method == "POST" and path.startswith("/api/"):
            user = self.auth.get_session_user(body.get("token", ""))
            if not user:
                return 401, {"success": False, "error": "Unauthorized"}

            message = body.get("message", "")
            if not message:
                return 400, {"success": False, "error": "message is required"}

            # Distinct endpoints route to the right intent by wrapping the
            # message with a directive the Decision Engine understands.
            directives = {
                "/api/chat": "{}",
                "/api/code": "Write code for: {}",
                "/api/debug": "Debug this code: {}",
                "/api/documentation": "Document this: {}",
                "/api/planner": "Make a plan for: {}",
                "/api/analyze": "Analyze this code: {}",
                "/api/project": "Analyze this project",
                "/api/github": "Get info about {}",
                "/api/workflow": "Build an application: {}",
            }
            route = directives.get(path)
            if route is None:
                return 404, {"success": False, "error": f"No route for {method} {path}"}
            if path == "/api/project":
                task_message = "Analyze this project"
            elif path == "/api/github":
                task_message = "Get info about " + message
            else:
                task_message = route.format(message)

            coordinator = self.get_coordinator()
            start = time.time()
            try:
                result = coordinator.handle_task(task_message)
                duration_ms = int((time.time() - start) * 1000)
                self.db.log_execution(
                    user["id"], result.get("agent", "api"), "success", duration_ms
                )
            except Exception as exc:
                duration_ms = int((time.time() - start) * 1000)
                self.db.log_execution(user["id"], "api", "error", duration_ms)
                return 500, {"success": False, "error": str(exc)}

            return 200, {
                "success": True,
                "agent": result.get("agent"),
                "response": result.get("response"),
            }

        return 404, {"success": False, "error": f"No route for {method} {path}"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _workflow_directive(wf_type, message):
        """Map an explicit workflow type to a directive the Decision Engine
        understands; unknown types fall back to natural routing (auto)."""
        prefix = WORKFLOW_DIRECTIVES.get(wf_type)
        return prefix.format(message) if prefix else message

    def _workflow_status_counts(self):
        """Count workflows per status for /api/system/health."""
        counts = {}
        for w in self.db.list_workflows(limit=100000):
            status = w.get("status") or "unknown"
            counts[status] = counts.get(status, 0) + 1
        return counts

    def _db_health(self):
        """Cheap DB liveness probe for /api/system/health."""
        try:
            row = self.db._query_one("SELECT COUNT(*) AS n FROM executions")
            return {"ok": True, "executions": row["n"] if row else 0}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------
    def serve(self):
        """Run the server (blocking)."""
        self._httpd = ThreadingHTTPServer(
            (self.host, self.port),
            _make_handler(self),
        )
        print(f"API server running at http://{self.host}:{self.port}")
        self._httpd.serve_forever()

    def serve_background(self):
        """Start the server in a daemon thread; returns immediately."""
        thread = threading.Thread(target=self.serve, daemon=True)
        thread.start()
        return thread


def _make_handler(server):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # keep stdout clean

        def _respond(self, status, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _dispatch(self, method):
            # Internal monitoring: time every request (Milestone 4).
            start = time.time()
            ok = True
            try:
                parsed = urlparse(self.path)
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else {}
                except json.JSONDecodeError:
                    body = {}
                status, payload = server._handle_request(method, parsed.path, body)
                if status >= 500:
                    ok = False
                self._respond(status, payload)
            except Exception as exc:
                ok = False
                try:
                    self._respond(500, {"success": False, "error": str(exc)})
                except Exception:
                    pass
            finally:
                get_metrics().record_request(
                    (time.time() - start) * 1000, ok=ok
                )

        do_GET = lambda self: self._dispatch("GET")
        do_POST = lambda self: self._dispatch("POST")

    return Handler
