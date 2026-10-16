"""Tests for quality.checks — Data reliability checks."""
from __future__ import annotations

import pytest

from kspo_ingest.quality.checks import (
    CheckStatus,
    check_body_length,
    check_boilerplate_removal,
    check_broken_chars,
    check_completeness,
    check_duplicate_lines,
    check_korean_ratio,
    check_link_counts,
    check_title_match,
    run_all_checks,
)


class TestCheckBodyLength:
    def test_empty(self):
        r = check_body_length("")
        assert r.status == CheckStatus.FAIL
        assert r.score == 0.0

    def test_too_short(self):
        r = check_body_length("짧은")
        assert r.status == CheckStatus.FAIL

    def test_normal(self):
        r = check_body_length("정상 본문 " * 100)
        assert r.status == CheckStatus.PASS
        assert r.score == 1.0

    def test_very_long(self):
        r = check_body_length("x" * 300_000)
        assert r.status == CheckStatus.WARNING


class TestCheckBoilerplate:
    def test_clean(self):
        r = check_boilerplate_removal("정상적인 본문 텍스트입니다.", "<html></html>")
        assert r.status == CheckStatus.PASS

    def test_nav_residue(self):
        r = check_boilerplate_removal("홈 > 공지사항 > 상세보기\n본문 내용", "<html></html>")
        assert r.status in (CheckStatus.WARNING, CheckStatus.FAIL)
        assert "네비게이션 잔여" in r.detail

    def test_footer_residue(self):
        body = "본문 내용\n\ncopyright 2024 KSPO. 개인정보처리방침"
        r = check_boilerplate_removal(body, "<html></html>")
        assert "푸터 잔여" in r.detail


class TestCheckBrokenChars:
    def test_clean(self):
        r = check_broken_chars("정상적인 한국어 텍스트")
        assert r.status == CheckStatus.PASS

    def test_replacement_char(self):
        r = check_broken_chars("깨진 문자 \ufffd\ufffd\ufffd 포함")
        assert r.status in (CheckStatus.WARNING, CheckStatus.FAIL)

    def test_many_broken(self):
        r = check_broken_chars("�" * 100 + "정상" * 10)
        assert r.status == CheckStatus.FAIL


class TestCheckDuplicateLines:
    def test_no_duplicates(self):
        r = check_duplicate_lines("첫 번째 줄입니다 내용이 충분히 깁니다\n두 번째 줄입니다 내용이 다릅니다")
        assert r.status == CheckStatus.PASS

    def test_with_duplicates(self):
        line = "이 줄은 반복되는 긴 텍스트입니다 최소 20자 이상"
        body = "\n".join([line] * 5 + ["다른 내용의 줄입니다 최소 20자 이상"])
        r = check_duplicate_lines(body)
        assert r.status in (CheckStatus.WARNING, CheckStatus.FAIL)
        assert "중복 문장" in r.detail


class TestCheckKoreanRatio:
    def test_korean(self):
        r = check_korean_ratio("한국체육진흥공단에서 알려드립니다.")
        assert r.status == CheckStatus.PASS
        assert r.score > 0.5

    def test_english(self):
        r = check_korean_ratio("This is an English text without any Korean.")
        assert r.status == CheckStatus.FAIL

    def test_empty(self):
        r = check_korean_ratio("")
        assert r.status == CheckStatus.FAIL


class TestCheckTitleMatch:
    def test_exact_match(self):
        html = "<html><head><title>공지사항</title></head></html>"
        r = check_title_match("공지사항", html)
        assert r.status == CheckStatus.PASS

    def test_partial_match(self):
        html = "<html><head><title>공지사항 | KSPO</title></head></html>"
        r = check_title_match("공지사항", html)
        assert r.status == CheckStatus.PASS  # 부분 일치

    def test_mismatch(self):
        html = "<html><head><title>전혀 다른 제목</title></head></html>"
        r = check_title_match("공지사항", html)
        assert r.status in (CheckStatus.WARNING, CheckStatus.FAIL)

    def test_both_none(self):
        r = check_title_match(None, "<html></html>")
        assert r.status == CheckStatus.WARNING


class TestCheckCompleteness:
    def test_all_present(self):
        r = check_completeness(
            title="제목", body_text="본문 " * 100,
            posted_at="2026-07-01", summary="요약",
            keywords=["키워드"], content_hash="abc123",
        )
        assert r.status == CheckStatus.PASS

    def test_missing_title(self):
        r = check_completeness(
            title=None, body_text="본문 " * 100,
            posted_at="2026-07-01", summary="요약",
            keywords=["키워드"], content_hash="abc123",
        )
        assert "제목 누락" in r.detail

    def test_empty_body(self):
        r = check_completeness(
            title="제목", body_text="",
            posted_at=None, summary=None,
            keywords=[], content_hash=None,
        )
        assert r.status == CheckStatus.FAIL
        assert "본문 비어있음" in r.detail

    def test_multiple_missing(self):
        r = check_completeness(
            title=None, body_text="짧은 본문",
            posted_at=None, summary=None,
            keywords=[], content_hash=None,
        )
        assert r.score < 0.5


class TestCheckLinkCounts:
    def test_with_links(self):
        html = '''<html><body>
            <a href="/page1">P1</a>
            <a href="/page2">P2</a>
            <a href="https://external.com">Ext</a>
        </body></html>'''
        r = check_link_counts("body", html, "example.com")
        assert "3" in r.detail  # 3 HTML links


class TestRunAllChecks:
    def test_good_document(self):
        html = "<html><head><title>공지사항</title></head><body><p>" + "한국어 본문 " * 100 + "</p></body></html>"
        report = run_all_checks(
            url="https://www.kspo.or.kr/page",
            raw_html=html,
            body_text="한국어 본문 " * 100,
            title="공지사항",
            host="www.kspo.or.kr",
        )
        assert report.overall_score > 0.5
        assert report.pass_count >= 4

    def test_bad_document(self):
        report = run_all_checks(
            url="https://example.com/empty",
            raw_html="<html></html>",
            body_text="",
            title=None,
        )
        assert report.overall_status == CheckStatus.FAIL
        assert report.fail_count >= 2

    def test_remedies_populated(self):
        report = run_all_checks(
            url="https://example.com/bad",
            raw_html="<html></html>",
            body_text="",
            title=None,
        )
        assert len(report.remedies) > 0
