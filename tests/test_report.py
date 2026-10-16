"""Tests for quality.report — 사이트별 리포트 집계."""
from __future__ import annotations

from kspo_ingest.quality.checks import CheckResult, CheckStatus, DocumentCheckReport
from kspo_ingest.quality.report import aggregate_site_report, format_report_text


def _make_doc(url: str, status: CheckStatus, score: float) -> DocumentCheckReport:
    doc = DocumentCheckReport(page_id=None, url=url)
    doc.checks = [
        CheckResult("body_length", status, score, "detail"),
        CheckResult("korean_ratio", CheckStatus.PASS, 1.0, "ok"),
    ]
    doc.overall_status = status
    doc.overall_score = score
    return doc


class TestAggregateSiteReport:
    def test_basic(self):
        docs = [
            _make_doc("https://a.com/1", CheckStatus.PASS, 0.9),
            _make_doc("https://a.com/2", CheckStatus.WARNING, 0.6),
            _make_doc("https://a.com/3", CheckStatus.FAIL, 0.2),
        ]
        sr = aggregate_site_report("a.com", docs)
        assert sr.total_docs == 3
        assert sr.pass_count == 1
        assert sr.warning_count == 1
        assert sr.fail_count == 1
        assert 0.5 < sr.avg_score < 0.7

    def test_empty(self):
        sr = aggregate_site_report("empty.com", [])
        assert sr.total_docs == 0
        assert sr.success_rate == 0.0

    def test_all_pass(self):
        docs = [_make_doc(f"https://a.com/{i}", CheckStatus.PASS, 0.95) for i in range(5)]
        sr = aggregate_site_report("a.com", docs)
        assert sr.success_rate == 1.0

    def test_check_scores(self):
        docs = [_make_doc("https://a.com/1", CheckStatus.PASS, 0.8)]
        sr = aggregate_site_report("a.com", docs)
        assert "body_length" in sr.check_scores
        assert sr.check_scores["body_length"] == 0.8


class TestFormatReport:
    def test_produces_text(self):
        docs = [_make_doc("https://a.com/1", CheckStatus.PASS, 0.9)]
        sr = aggregate_site_report("a.com", docs)
        text = format_report_text(sr)
        assert "a.com" in text
        assert "PASS" in text
