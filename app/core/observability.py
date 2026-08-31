from __future__ import annotations

import logging
import math
import os
import resource
import sys
import time
import uuid
from collections import Counter, deque
from datetime import UTC, datetime

from app.core.config import settings
from app.core.logging import redact_query

logger = logging.getLogger("zent.request")

# request paths we don't want in the metrics (the dashboard polls these)
_IGNORE_PREFIXES = ("/observability", "/health", "/docs", "/redoc", "/openapi.json", "/favicon")


class _RouteStat:
    __slots__ = ("count", "sum_ms", "max_ms", "errors")

    def __init__(self) -> None:
        self.count = 0
        self.sum_ms = 0.0
        self.max_ms = 0.0
        self.errors = 0


class Metrics:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.started_at = time.time()
        self.total = 0
        self.status_classes: Counter[str] = Counter()
        self.routes: dict[str, _RouteStat] = {}
        self.latencies: deque[float] = deque(maxlen=settings.METRICS_SAMPLE_SIZE)
        self.recent: deque[dict] = deque(maxlen=settings.METRICS_RECENT_SIZE)
        self.recent_errors: deque[dict] = deque(maxlen=min(50, settings.METRICS_RECENT_SIZE))

    def record(
        self,
        *,
        method: str,
        route: str,
        path: str,
        status: int,
        duration_ms: float,
        ip: str | None,
        request_id: str,
        error: str | None = None,
    ) -> None:
        self.total += 1
        cls = f"{status // 100}xx"
        self.status_classes[cls] += 1
        self.latencies.append(duration_ms)

        stat = self.routes.get(route)
        if stat is None:
            stat = self.routes[route] = _RouteStat()
        stat.count += 1
        stat.sum_ms += duration_ms
        stat.max_ms = max(stat.max_ms, duration_ms)
        if status >= 500 or error:
            stat.errors += 1

        entry = {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "method": method,
            "path": path,
            "route": route,
            "status": status,
            "ms": round(duration_ms, 1),
            "ip": ip,
            "id": request_id,
        }
        self.recent.appendleft(entry)
        if status >= 500 or error:
            self.recent_errors.appendleft({**entry, "error": error or f"HTTP {status}"})

    # --- reporting ---
    def _percentiles(self) -> dict[str, float]:
        if not self.latencies:
            return {"p50": 0.0, "p90": 0.0, "p99": 0.0, "max": 0.0, "avg": 0.0}
        ordered = sorted(self.latencies)

        def pct(p: float) -> float:
            k = (len(ordered) - 1) * p
            lo = math.floor(k)
            hi = math.ceil(k)
            if lo == hi:
                return ordered[int(k)]
            return ordered[lo] * (hi - k) + ordered[hi] * (k - lo)

        return {
            "p50": round(pct(0.50), 1),
            "p90": round(pct(0.90), 1),
            "p99": round(pct(0.99), 1),
            "max": round(ordered[-1], 1),
            "avg": round(sum(ordered) / len(ordered), 1),
        }

    def _rss_mb(self) -> float:
        raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports bytes, Linux reports kilobytes
        return round(raw / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)

    def snapshot(self) -> dict:
        uptime = max(1e-6, time.time() - self.started_at)
        errors = self.status_classes.get("4xx", 0) + self.status_classes.get("5xx", 0)
        routes = [
            {
                "route": name,
                "count": s.count,
                "avgMs": round(s.sum_ms / s.count, 1) if s.count else 0.0,
                "maxMs": round(s.max_ms, 1),
                "errors": s.errors,
            }
            for name, s in self.routes.items()
        ]
        return {
            "startedAt": datetime.fromtimestamp(self.started_at, UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "uptimeSeconds": round(uptime, 1),
            "totalRequests": self.total,
            "requestsPerSecond": round(self.total / uptime, 3),
            "statusClasses": dict(sorted(self.status_classes.items())),
            "errorRate": round(errors / self.total, 4) if self.total else 0.0,
            "latencyMs": self._percentiles(),
            "sampleSize": len(self.latencies),
            "topRoutes": sorted(routes, key=lambda r: r["count"], reverse=True)[:20],
            "slowestRoutes": sorted(routes, key=lambda r: r["avgMs"], reverse=True)[:10],
            "process": {
                "pid": os.getpid(),
                "python": sys.version.split()[0],
                "rssMb": self._rss_mb(),
            },
        }

    def logs(self) -> dict:
        return {
            "recentRequests": list(self.recent),
            "recentErrors": list(self.recent_errors),
        }


metrics = Metrics()


def _route_template(scope, path: str) -> str:
    """Low-cardinality label: real path with {param} placeholders, or <unmatched>."""
    if scope.get("route") is None:
        return "<unmatched>"
    template = path
    for key, value in (scope.get("path_params") or {}).items():
        template = template.replace(str(value), "{" + key + "}", 1)
    return template


class ObservabilityMiddleware:
    """Pure-ASGI: times every request, records metrics, stamps X-Request-ID."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not settings.OBSERVABILITY_ENABLED:
            return await self.app(scope, receive, send)

        request_id = uuid.uuid4().hex[:16]
        start = time.perf_counter()
        status_holder = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                headers = message.setdefault("headers", [])
                headers.append((b"x-request-id", request_id.encode()))
            await send(message)

        error: str | None = None
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:  # noqa: BLE001 - record then re-raise
            error = f"{type(exc).__name__}: {exc}"
            status_holder["code"] = 500
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            path = scope.get("path", "")
            if not path.startswith(_IGNORE_PREFIXES):
                route = _route_template(scope, path)
                client = scope.get("client")
                query = redact_query((scope.get("query_string") or b"").decode("latin-1"))
                metrics.record(
                    method=scope.get("method", "?"),
                    route=route,
                    path=path + (f"?{query}" if query else ""),
                    status=status_holder["code"],
                    duration_ms=duration_ms,
                    ip=client[0] if client else None,
                    request_id=request_id,
                    error=error,
                )
                log = logger.warning if status_holder["code"] >= 500 else logger.info
                log(
                    "%s %s -> %s %.1fms",
                    scope.get("method", "?"),
                    route,
                    status_holder["code"],
                    duration_ms,
                    extra={"extra_fields": {"request_id": request_id}},
                )
