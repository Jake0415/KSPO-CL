from __future__ import annotations

from datetime import datetime, timedelta, timezone

from kspo_ingest.crawl.board import classify_freshness

# Gate policy: 'stale' -> drop; 'no_date'/'ok' -> keep (undated pages are permanent reference info).

NOW = datetime(2026, 8, 4, tzinfo=timezone.utc)


def test_gate_drops_stale_with_reason_stale():
    verdict = classify_freshness(NOW - timedelta(days=100), freshness_days=90, now=NOW)
    assert verdict == "stale"


def test_classify_none_returns_no_date():
    assert classify_freshness(None, freshness_days=90, now=NOW) == "no_date"


def test_gate_passes_recent():
    assert classify_freshness(NOW - timedelta(days=5), freshness_days=90, now=NOW) == "ok"
