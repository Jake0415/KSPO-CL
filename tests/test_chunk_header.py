from __future__ import annotations

from datetime import UTC, datetime

from kspo_ingest.chunk.header import (
    AttachmentHeaderInput,
    PageHeaderInput,
    build_attachment_header,
    build_page_header,
)

SAMPLE_DATE = datetime(2025, 4, 1, 9, 0, tzinfo=UTC)


def test_page_header_all_fields_present():
    h = build_page_header(
        PageHeaderInput(
            title="공고 제목",
            domain_host="www.kspo.or.kr",
            posted_at=SAMPLE_DATE,
            summary="요약입니다",
        )
    )
    assert "[제목] 공고 제목" in h
    assert "[도메인] www.kspo.or.kr" in h
    assert "[게시일] 2025-04-01" in h
    assert "[요약] 요약입니다" in h
    assert h.endswith("— 본문 —\n")


def test_page_header_omits_posted_at_when_none():
    h = build_page_header(
        PageHeaderInput(title="t", domain_host="h", posted_at=None, summary="s")
    )
    assert "[게시일]" not in h
    assert "[요약] s" in h


def test_page_header_omits_summary_when_none():
    h = build_page_header(
        PageHeaderInput(title="t", domain_host="h", posted_at=SAMPLE_DATE, summary=None)
    )
    assert "[요약]" not in h
    assert "[게시일]" in h


def test_page_header_omits_title_when_none():
    h = build_page_header(
        PageHeaderInput(title=None, domain_host="h", posted_at=None, summary=None)
    )
    assert "[제목]" not in h
    assert h.startswith("[도메인] h")


def test_attachment_header_file_name_only():
    h = build_attachment_header(
        AttachmentHeaderInput(file_name="안내문.pdf", parent_title=None, parent_posted_at=None)
    )
    assert "[첨부파일] 안내문.pdf" in h
    assert "[부모 게시글]" not in h
    assert "[게시일]" not in h
    assert h.endswith("— 본문 —\n")


def test_attachment_header_with_parent_info():
    h = build_attachment_header(
        AttachmentHeaderInput(
            file_name="첨부.hwp",
            parent_title="모집공고",
            parent_posted_at=SAMPLE_DATE,
        )
    )
    assert "[첨부파일] 첨부.hwp" in h
    assert "[부모 게시글] 모집공고" in h
    assert "[게시일] 2025-04-01" in h
