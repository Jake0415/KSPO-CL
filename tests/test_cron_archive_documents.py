from __future__ import annotations

import inspect

from kspo_ingest.tasks import cron


def test_archive_documents_enforces_posted_at_recency():
    """비게시판 문서도 발행일 90일 초과 또는 무날짜면 아카이브 대상."""
    src = inspect.getsource(cron.archive_expired_documents)
    assert "posted_at" in src            # 발행일 규칙 추가됨
    assert "board_freshness_days" in src  # 90일 cutoff 재사용
    assert "or_(" in src                 # 품질점수 OR 발행일규칙
    assert "and_(" in src   # freshness_score decay is quadrant-scoped, but recency/null are not


def test_archive_documents_keeps_board_exclusion_and_null_guard():
    src = inspect.getsource(cron.archive_expired_documents)
    assert "board_source_id" in src       # 게시판은 board 크론이 처리 (기존 조건 유지)
    assert "posted_at.is_(None)" not in src   # 무날짜(NULL) 글은 아카이브하지 않음(수집·유지)
