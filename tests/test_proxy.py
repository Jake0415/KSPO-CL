"""Tests for crawl.proxy — Proxy rotation and health checking."""
from __future__ import annotations

import pytest

from kspo_ingest.crawl.proxy import ProxyEntry, ProxyRotator


class TestProxyEntry:
    def test_record_success(self):
        entry = ProxyEntry(url="http://proxy1:8080")
        entry.record_success(100.0)
        assert entry.is_healthy
        assert entry.fail_count == 0
        assert entry.avg_latency_ms == 100.0

    def test_record_failure_marks_unhealthy_after_3(self):
        entry = ProxyEntry(url="http://proxy1:8080")
        entry.record_failure()
        assert entry.is_healthy  # 1 failure — still healthy
        entry.record_failure()
        assert entry.is_healthy  # 2 failures — still healthy
        entry.record_failure()
        assert not entry.is_healthy  # 3 failures — unhealthy

    def test_success_resets_fail_count(self):
        entry = ProxyEntry(url="http://proxy1:8080")
        entry.record_failure()
        entry.record_failure()
        entry.record_success(50.0)
        assert entry.fail_count == 0
        assert entry.is_healthy

    def test_avg_latency_rolling(self):
        entry = ProxyEntry(url="http://proxy1:8080")
        for i in range(15):
            entry.record_success(float(i * 10))
        # only last 10 kept
        assert len(entry._latencies) == 10


class TestProxyRotator:
    def test_empty_rotator(self):
        rotator = ProxyRotator()
        assert not rotator.has_proxies
        assert rotator.next() is None

    def test_single_proxy(self):
        rotator = ProxyRotator(["http://proxy1:8080"])
        assert rotator.has_proxies
        assert rotator.healthy_count == 1
        assert rotator.next() == "http://proxy1:8080"

    def test_rotation(self):
        rotator = ProxyRotator(["http://p1:80", "http://p2:80", "http://p3:80"])
        seen = set()
        for _ in range(6):
            url = rotator.next()
            assert url is not None
            seen.add(url)
        assert len(seen) == 3

    def test_add_proxy(self):
        rotator = ProxyRotator()
        rotator.add("http://new:80")
        assert rotator.has_proxies
        assert rotator.next() == "http://new:80"

    def test_report_failure_excludes(self):
        rotator = ProxyRotator(["http://bad:80", "http://good:80"])
        for _ in range(3):
            rotator.report_failure("http://bad:80")
        assert rotator.healthy_count == 1
        # only good proxy returned
        for _ in range(5):
            assert rotator.next() == "http://good:80"

    def test_all_unhealthy_fallback(self):
        rotator = ProxyRotator(["http://p1:80"])
        for _ in range(3):
            rotator.report_failure("http://p1:80")
        assert rotator.healthy_count == 0
        # fallback — returns oldest failure
        url = rotator.next()
        assert url == "http://p1:80"

    def test_get_stats(self):
        rotator = ProxyRotator(["http://p1:80"])
        rotator.report_success("http://p1:80", 100.0)
        stats = rotator.get_stats()
        assert len(stats) == 1
        assert stats[0]["healthy"] is True
        assert stats[0]["avg_latency_ms"] == 100.0
