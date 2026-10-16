"""Prometheus metrics — 크롤/파이프라인 메트릭 수집.

선택적 의존성 — prometheus_client 미설치 시 noop.
"""
from __future__ import annotations

from typing import Any

from kspo_ingest.observability.logger import get_logger

log = get_logger("platform", "metrics")

try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest

    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False


class _NoopMetric:
    """prometheus_client 미설치 시 noop 구현."""

    def inc(self, amount: float = 1) -> None:
        pass

    def dec(self, amount: float = 1) -> None:
        pass

    def set(self, value: float) -> None:
        pass

    def observe(self, amount: float) -> None:
        pass

    def labels(self, **kwargs: Any) -> _NoopMetric:
        return self


def _counter(name: str, doc: str, labels: list[str] | None = None) -> Any:
    if not _HAS_PROMETHEUS:
        return _NoopMetric()
    if labels:
        return Counter(name, doc, labels)
    return Counter(name, doc)


def _gauge(name: str, doc: str, labels: list[str] | None = None) -> Any:
    if not _HAS_PROMETHEUS:
        return _NoopMetric()
    if labels:
        return Gauge(name, doc, labels)
    return Gauge(name, doc)


def _histogram(name: str, doc: str, buckets: list[float] | None = None) -> Any:
    if not _HAS_PROMETHEUS:
        return _NoopMetric()
    if buckets:
        return Histogram(name, doc, buckets=buckets)
    return Histogram(name, doc)


# --- Crawl Metrics ---

pages_fetched_total = _counter(
    "kspo_pages_fetched_total",
    "Total pages fetched",
    labels=["domain", "status"],
)

pages_cleaned_total = _counter(
    "kspo_pages_cleaned_total",
    "Total pages cleaned",
    labels=["method"],
)

pages_refined_total = _counter(
    "kspo_pages_refined_total",
    "Total pages refined",
    labels=["result"],  # "ok", "dropped", "error"
)

pages_indexed_total = _counter(
    "kspo_pages_indexed_total",
    "Total pages indexed to Qdrant",
)

fetch_duration_seconds = _histogram(
    "kspo_fetch_duration_seconds",
    "Fetch duration in seconds",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# --- LLM Metrics ---

llm_requests_total = _counter(
    "kspo_llm_requests_total",
    "Total LLM API requests",
    labels=["provider", "purpose"],
)

llm_tokens_total = _counter(
    "kspo_llm_tokens_total",
    "Total LLM tokens consumed",
    labels=["provider", "type"],  # type: "prompt" | "completion"
)

llm_cost_usd_total = _counter(
    "kspo_llm_cost_usd_total",
    "Total LLM cost in USD",
    labels=["provider"],
)

# --- Agent Metrics ---

agent_tasks_total = _counter(
    "kspo_agent_tasks_total",
    "Total agent tasks",
    labels=["status"],  # "success", "failed"
)

agent_steps_total = _counter(
    "kspo_agent_steps_total",
    "Total agent steps taken",
)

# --- System Metrics ---

active_jobs = _gauge(
    "kspo_active_jobs",
    "Currently running crawl jobs",
)

frontier_size = _gauge(
    "kspo_frontier_size",
    "Current frontier queue size",
    labels=["job_id"],
)

proxy_healthy_count = _gauge(
    "kspo_proxy_healthy",
    "Number of healthy proxies",
)


def get_metrics_text() -> str:
    """Prometheus 텍스트 포맷 반환."""
    if not _HAS_PROMETHEUS:
        return "# prometheus_client not installed\n"
    return generate_latest().decode("utf-8")
