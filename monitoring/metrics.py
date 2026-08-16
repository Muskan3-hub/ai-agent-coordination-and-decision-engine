"""Internal monitoring metrics (Milestone 4 - Task 2).

In-process counters and snapshots used for logging / monitoring /
performance tracking / tool usage / workflow statistics. Everything here
is intentionally INTERNAL - nothing in this module renders to the user
interface; the data is exposed only through the REST API
(``/api/system/health``) and the benchmark script.

Design:
- Thread-safe (a lock guards every mutation) because the REST API runs a
  ThreadingHTTPServer and the Streamlit app runs its own thread.
- Cheap: just integer counters and a small rolling latency buffer.
"""

import threading
import time

try:
    import psutil
except Exception:  # psutil is optional
    psutil = None


class Metrics:
    """Process-wide request/error/latency/memory counters."""

    def __init__(self, latency_window=200):
        self._lock = threading.Lock()
        self._started = time.time()
        self._latency_window = latency_window
        self._latencies = []          # recent per-request durations (ms)
        self.requests = 0            # total requests handled
        self.errors = 0              # requests that failed
        self.llm_calls = 0           # LLM calls made (agent/classifier)
        self.tool_calls = 0          # tool invocations
        self.workflows_started = 0   # workflows / chains executed
        self.workflows_failed = 0
        self._agent_time = {}        # agent name -> total ms
        self._agent_count = {}       # agent name -> number of executions
        self._tool_count = {}        # tool name -> number of uses

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def record_request(self, duration_ms, ok=True):
        with self._lock:
            self.requests += 1
            if not ok:
                self.errors += 1
            self._latencies.append(duration_ms)
            if len(self._latencies) > self._latency_window:
                self._latencies = self._latencies[-self._latency_window:]

    def record_llm(self, n=1):
        with self._lock:
            self.llm_calls += n

    def record_tool(self, name="unknown"):
        with self._lock:
            self.tool_calls += 1
            self._tool_count[name] = self._tool_count.get(name, 0) + 1

    def record_agent(self, name, duration_ms):
        with self._lock:
            self._agent_time[name] = self._agent_time.get(name, 0) + duration_ms
            self._agent_count[name] = self._agent_count.get(name, 0) + 1

    def record_workflow(self, ok=True):
        with self._lock:
            self.workflows_started += 1
            if not ok:
                self.workflows_failed += 1

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def snapshot(self):
        """Return a JSON-serializable dict of the current metrics."""
        with self._lock:
            lat = self._latencies
            avg = (sum(lat) / len(lat)) if lat else 0.0
            p95 = sorted(lat)[int(len(lat) * 0.95) - 1] if len(lat) >= 20 else (max(lat) if lat else 0)
            agent_usage = [
                {
                    "agent": name,
                    "count": self._agent_count.get(name, 0),
                    "avg_ms": round(self._agent_time.get(name, 0) / self._agent_count[name], 1)
                    if self._agent_count.get(name) else 0,
                }
                for name in self._agent_count
            ]
            return {
                "uptime_sec": int(time.time() - self._started),
                "requests": self.requests,
                "errors": self.errors,
                "error_rate": round(100 * self.errors / self.requests, 2) if self.requests else 0.0,
                "avg_latency_ms": round(avg, 1),
                "p95_latency_ms": round(p95, 1),
                "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls,
                "workflows_started": self.workflows_started,
                "workflows_failed": self.workflows_failed,
                "workflow_success_rate": round(
                    100 * (self.workflows_started - self.workflows_failed) / self.workflows_started, 1
                ) if self.workflows_started else 0.0,
                "agent_usage": agent_usage,
                "memory": memory_snapshot(),
            }

    def reset(self):
        with self._lock:
            self.__init__()


# ----------------------------------------------------------------------
# Module-level singleton
# ----------------------------------------------------------------------
_metrics = None
_metrics_lock = threading.Lock()


def get_metrics():
    """Return the process-wide Metrics singleton."""
    global _metrics
    with _metrics_lock:
        if _metrics is None:
            _metrics = Metrics()
        return _metrics


def memory_snapshot():
    """Current process memory usage (works without psutil)."""
    try:
        if psutil is not None:
            proc = psutil.Process()
            rss = proc.memory_info().rss
            return {
                "rss_bytes": rss,
                "rss_mb": round(rss / (1024 * 1024), 1),
                "percent": proc.memory_percent(),
            }
    except Exception:
        pass
    # Fallback: tracemalloc peak (cheap, stdlib-only).
    try:
        import tracemalloc

        tracemalloc.start()
        snapshot = tracemalloc.take_snapshot()
        size = sum(stat.size for stat in snapshot.statistics("filename"))
        tracemalloc.stop()
        return {"rss_bytes": size, "rss_mb": round(size / (1024 * 1024), 1), "percent": None}
    except Exception:
        return {"rss_bytes": None, "rss_mb": None, "percent": None}
