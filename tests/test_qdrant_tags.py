from __future__ import annotations

from datetime import UTC, datetime

from kspo_ingest.qdrant.tags import build_tags


def test_page_chunk_baseline_tags():
    tags = build_tags(
        domain_host="www.kspo.or.kr",
        posted_at=None,
        attachment_id=None,
        parent_page_id=None,
        is_attachment=False,
        embedding_version=1,
    )
    assert tags == ["d:www.kspo.or.kr", "is_att:0", "v:1"]


def test_page_chunk_with_posted_at_adds_year_and_yyyy_mm():
    tags = build_tags(
        domain_host="a.com",
        posted_at=datetime(2026, 4, 7, tzinfo=UTC),
        attachment_id=None,
        parent_page_id=None,
        is_attachment=False,
        embedding_version=1,
    )
    assert "p:2026" in tags
    assert "p:2026-04" in tags


def test_attachment_chunk_includes_att_and_pid():
    tags = build_tags(
        domain_host="a.com",
        posted_at=None,
        attachment_id=42,
        parent_page_id=99,
        is_attachment=True,
        embedding_version=1,
    )
    assert "is_att:1" in tags
    assert "att:42" in tags
    assert "pid:99" in tags


def test_posted_at_none_omits_p_prefix():
    tags = build_tags(
        domain_host="a.com",
        posted_at=None,
        attachment_id=None,
        parent_page_id=None,
        is_attachment=False,
        embedding_version=1,
    )
    assert not any(t.startswith("p:") for t in tags)


def test_month_zero_padded():
    tags = build_tags(
        domain_host="a.com",
        posted_at=datetime(2026, 1, 5, tzinfo=UTC),
        attachment_id=None,
        parent_page_id=None,
        is_attachment=False,
        embedding_version=1,
    )
    assert "p:2026-01" in tags
    assert "p:2026-1" not in tags


def test_deterministic_order():
    """동일 입력 → 동일 순서 (테스트 비교 가능)."""
    inputs = {
        "domain_host": "x.com",
        "posted_at": datetime(2026, 4, 1, tzinfo=UTC),
        "attachment_id": 7,
        "parent_page_id": 3,
        "is_attachment": True,
        "embedding_version": 2,
    }
    a = build_tags(**inputs)
    b = build_tags(**inputs)
    assert a == b
    assert a == [
        "d:x.com",
        "is_att:1",
        "v:2",
        "p:2026",
        "p:2026-04",
        "att:7",
        "pid:3",
    ]


def test_no_tier2_prefixes():
    """v2.1 — c:, lang:, ru:, qs: 등 Tier 2 prefix 미포함 (`_appendix.md` §C)."""
    tags = build_tags(
        domain_host="a.com",
        posted_at=datetime(2026, 4, 1, tzinfo=UTC),
        attachment_id=1,
        parent_page_id=2,
        is_attachment=True,
        embedding_version=1,
    )
    forbidden = ("c:", "lang:", "ru:", "qs:")
    for t in tags:
        for prefix in forbidden:
            assert not t.startswith(prefix), f"Tier 2 prefix '{prefix}' leaked: {t}"


def test_embedding_version_in_tag():
    tags = build_tags(
        domain_host="a.com",
        posted_at=None,
        attachment_id=None,
        parent_page_id=None,
        is_attachment=False,
        embedding_version=5,
    )
    assert "v:5" in tags
