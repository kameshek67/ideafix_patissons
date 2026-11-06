"""Метрики Prometheus: число и длительность запросов по маршрутам (GET /metrics)."""

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST


def install_metrics(app: FastAPI) -> None:
    registry = CollectorRegistry()  # свой реестр: несколько приложений в тестах не конфликтуют
    requests = Counter(
        "olymp_http_requests_total",
        "HTTP-запросы",
        ["method", "route", "status"],
        registry=registry,
    )
    latency = Histogram(
        "olymp_http_request_seconds",
        "Длительность запросов",
        ["route"],
        registry=registry,
        buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1, 2.5, 5),
    )

    @app.middleware("http")
    async def measure(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        # шаблон пути, а не значения id
        route = getattr(request.scope.get("route"), "path", "unmatched")
        requests.labels(request.method, route, str(response.status_code)).inc()
        latency.labels(route).observe(time.perf_counter() - start)
        return response

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
