from __future__ import annotations

from datetime import datetime, timezone

from kspo_ingest.clean.date_extract import extract_posted_at


def test_extract_from_meta_tag():
    html = '<html><head><meta property="article:published_time" content="2026-07-01T09:00:00+09:00"></head><body></body></html>'
    dt = extract_posted_at(html)
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 7
    assert dt.day == 1


def test_extract_from_date_class():
    html = '<html><body><span class="date">2026.06.15</span></body></html>'
    dt = extract_posted_at(html)
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 6


def test_extract_returns_none_for_no_date():
    html = '<html><body><p>No date here</p></body></html>'
    assert extract_posted_at(html) is None


def test_extract_empty_html():
    assert extract_posted_at("") is None


def test_extract_iso_format():
    html = '<html><head><meta name="date" content="2026-03-20"></head></html>'
    dt = extract_posted_at(html)
    assert dt is not None
    assert dt.month == 3
    assert dt.day == 20


def test_extract_from_korean_label():
    html = '<div class="view-info">작성일 2026-07-09 조회 12</div>'
    dt = extract_posted_at(html)
    assert dt is not None and dt.year == 2026 and dt.month == 7 and dt.day == 9


def test_extract_from_definition_list_label():
    html = '<dl><dt>등록일</dt><dd>2026.06.30</dd></dl>'
    dt = extract_posted_at(html)
    assert dt is not None and dt.month == 6 and dt.day == 30


from kspo_ingest.clean.date_extract import extract_posted_at_with_source


def test_publish_meta_beats_registered_label():
    # 발행일 메타 + 등록일 라벨이 동시 존재 → 발행일(meta) 우선
    html = ('<html><head><meta property="article:published_time" '
            'content="2026-07-01T09:00:00+09:00"></head>'
            '<body><span>등록일 2026-07-05</span></body></html>')
    dt, source = extract_posted_at_with_source(html)
    assert source == "published"
    assert dt.month == 7 and dt.day == 1


def test_registered_label_used_as_fallback():
    html = '<html><body><span>등록일 : 2026-06-15</span></body></html>'
    dt, source = extract_posted_at_with_source(html)
    assert source == "registered"
    assert dt.month == 6 and dt.day == 15


def test_publish_label_beats_registered_label():
    html = '<html><body><p>게시일 2026-06-10</p><p>등록일 2026-06-20</p></body></html>'
    dt, source = extract_posted_at_with_source(html)
    assert source == "published"
    assert dt.day == 10


def test_korean_year_month_day_format():
    html = '<html><body><span>등록일 2026년 8월 4일</span></body></html>'
    dt, source = extract_posted_at_with_source(html)
    assert dt is not None
    assert dt.year == 2026 and dt.month == 8 and dt.day == 4


def test_two_digit_year_format():
    html = '<html><body><span class="reg_date">24.08.04</span></body></html>'
    dt, _ = extract_posted_at_with_source(html)
    assert dt is not None and dt.year == 2024 and dt.month == 8


def test_future_date_is_rejected():
    # 오늘(테스트 실행일)보다 미래인 날짜는 파싱 오류로 간주 → None
    html = '<html><head><meta name="date" content="2099-11-28"></head></html>'
    dt, source = extract_posted_at_with_source(html)
    assert dt is None and source == "none"


def test_no_date_returns_none_source():
    dt, source = extract_posted_at_with_source('<html><body>no date</body></html>')
    assert dt is None and source == "none"
