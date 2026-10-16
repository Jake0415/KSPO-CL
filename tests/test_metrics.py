"""Tests for platform.metrics — Prometheus metrics (noop fallback)."""
from __future__ import annotations

from kspo_ingest.platform.metrics import (
    _NoopMetric,
    fetch_duration_seconds,
    get_metrics_text,
    pages_fetched_total,
)


class TestNoopMetric:
    def test_inc(self):
        m = _NoopMetric()
        m.inc()
        m.inc(5)

    def test_dec(self):
        m = _NoopMetric()
        m.dec()

    def test_set(self):
        m = _NoopMetric()
        m.set(42.0)

    def test_observe(self):
        m = _NoopMetric()
        m.observe(1.5)

    def test_labels(self):
        m = _NoopMetric()
        labeled = m.labels(domain="example.com", status="200")
        assert isinstance(labeled, _NoopMetric)
        labeled.inc()


class TestMetrics:
    def test_get_metrics_text(self):
        text = get_metrics_text()
        assert isinstance(text, str)

    def test_metrics_objects_exist(self):
        # 메트릭 객체들이 존재하는지 확인 (noop이든 real이든)
        assert pages_fetched_total is not None
        assert fetch_duration_seconds is not None
