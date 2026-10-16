"""refresh_url ARQ task 단위 테스트 — fetch/clean/refine/chunk_and_index 모두 mock.

각 분기:
- force=False + 변경 없음 (clean이 skipped 반환) → SUCCESS, refine/chunk 미호출
- force=False + 변경 있음 → SUCCESS, refine + chunk 호출
- force=True 시 clean에 force 인자 전달
- fetch None → SUCCESS, clean/refine 미호출
- 페이지 없음 → FAILED
- refine None → SUCCESS, chunk 미호출
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from kspo_ingest.tasks.pipeline import refresh_url as mod


class FakePage:
    def __init__(self, page_id=10, domain_id=1, url="https://example.com/x"):
        self.id = page_id
        self.domain_id = domain_id
        self.url = url
        self.host = "example.com"  # Domain 조회 시 domain.host 접근용
        self.posted_at = None


def _make_factory(page=None):
    s = MagicMock()
    s.get = AsyncMock(return_value=page)
    s.commit = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=s)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


@pytest.mark.asyncio
async def test_refresh_url_no_page_marks_failed(monkeypatch):
    factory = _make_factory(page=None)
    finish = AsyncMock()
    monkeypatch.setattr(mod, "finish_job", finish)
    monkeypatch.setattr(mod, "start_job", AsyncMock())

    await mod.refresh_url({"session_factory": factory}, job_id=1, page_id=999)

    args, kwargs = finish.call_args
    assert kwargs.get("status") == "FAILED"


@pytest.mark.asyncio
async def test_refresh_url_skipped_short_circuits(monkeypatch):
    page = FakePage()
    factory = _make_factory(page=page)
    monkeypatch.setattr(mod, "start_job", AsyncMock())
    monkeypatch.setattr(mod, "is_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr(mod, "fetch_page", AsyncMock(return_value=10))
    monkeypatch.setattr(
        mod, "clean_page", AsyncMock(return_value={"skipped": True, "page_id": 10})
    )
    refine_called = AsyncMock()
    chunk_called = AsyncMock()
    monkeypatch.setattr(mod, "refine_page", refine_called)
    monkeypatch.setattr(mod, "chunk_and_index", chunk_called)
    finish = AsyncMock()
    monkeypatch.setattr(mod, "finish_job", finish)

    await mod.refresh_url({"session_factory": factory}, job_id=1, page_id=10, force=False)

    refine_called.assert_not_awaited()
    chunk_called.assert_not_awaited()
    args, kwargs = finish.call_args
    assert kwargs.get("status") == "SUCCESS"


@pytest.mark.asyncio
async def test_refresh_url_force_passes_to_clean(monkeypatch):
    page = FakePage()
    factory = _make_factory(page=page)
    monkeypatch.setattr(mod, "start_job", AsyncMock())
    monkeypatch.setattr(mod, "is_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr(mod, "fetch_page", AsyncMock(return_value=10))
    clean_mock = AsyncMock(return_value={"skipped": True, "page_id": 10})
    monkeypatch.setattr(mod, "clean_page", clean_mock)
    monkeypatch.setattr(mod, "refine_page", AsyncMock())
    monkeypatch.setattr(mod, "chunk_and_index", AsyncMock())
    monkeypatch.setattr(mod, "finish_job", AsyncMock())

    await mod.refresh_url({"session_factory": factory}, job_id=1, page_id=10, force=True)

    args, kwargs = clean_mock.call_args
    assert kwargs.get("force") is True


@pytest.mark.asyncio
async def test_refresh_url_full_chain_when_changed(monkeypatch):
    page = FakePage()
    factory = _make_factory(page=page)
    monkeypatch.setattr(mod, "start_job", AsyncMock())
    monkeypatch.setattr(mod, "is_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr(mod, "fetch_page", AsyncMock(return_value=10))
    monkeypatch.setattr(
        mod,
        "clean_page",
        AsyncMock(
            return_value={
                "skipped": False,
                "page_id": 10,
                "title": "T",
                "body_text": "본문",
                "content_hash": "h",
            }
        ),
    )
    monkeypatch.setattr(
        mod,
        "refine_page",
        AsyncMock(
            return_value={
                "page_id": 10,
                "refined": {
                    "refined_text": "정제된 본문",
                    "summary": "요약",
                    "keywords": ["k1"],
                    "is_meaningful": True,
                },
            }
        ),
    )
    chunk_mock = AsyncMock()
    monkeypatch.setattr(mod, "chunk_and_index", chunk_mock)
    monkeypatch.setattr(mod, "bump_stats", AsyncMock())
    finish = AsyncMock()
    monkeypatch.setattr(mod, "finish_job", finish)

    # Quality scoring 경로 mock — refresh도 enqueue_seeds와 동일하게 점수/컬렉션 라우팅
    fake_score = MagicMock(
        quality_score=0.8, quadrant="Q1", freshness_score=0.5, trust_score=1.0
    )
    monkeypatch.setattr(mod, "score_document", MagicMock(return_value=fake_score))
    monkeypatch.setattr(mod, "upsert_doc_quality", AsyncMock())
    monkeypatch.setattr(
        mod, "resolve_embedding_targets",
        MagicMock(return_value=["tilellm", "kspo_knowledge"]),
    )

    await mod.refresh_url({"session_factory": factory}, job_id=1, page_id=10)

    chunk_mock.assert_awaited_once()
    args, kwargs = chunk_mock.call_args
    assert kwargs["refined_text"] == "정제된 본문"
    assert kwargs["quadrant"] == "Q1"
    assert kwargs["quality_score"] == 0.8
    assert kwargs["collections"] == ["tilellm", "kspo_knowledge"]
    args, kwargs = finish.call_args
    assert kwargs.get("status") == "SUCCESS"


@pytest.mark.asyncio
async def test_refresh_url_fetch_none_skips_chain(monkeypatch):
    page = FakePage()
    factory = _make_factory(page=page)
    monkeypatch.setattr(mod, "start_job", AsyncMock())
    monkeypatch.setattr(mod, "is_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr(mod, "fetch_page", AsyncMock(return_value=None))
    clean_mock = AsyncMock()
    monkeypatch.setattr(mod, "clean_page", clean_mock)
    finish = AsyncMock()
    monkeypatch.setattr(mod, "finish_job", finish)

    await mod.refresh_url({"session_factory": factory}, job_id=1, page_id=10)

    clean_mock.assert_not_awaited()
    args, kwargs = finish.call_args
    assert kwargs.get("status") == "SUCCESS"


@pytest.mark.asyncio
async def test_refresh_url_clean_none_skips_chain(monkeypatch):
    page = FakePage()
    factory = _make_factory(page=page)
    monkeypatch.setattr(mod, "start_job", AsyncMock())
    monkeypatch.setattr(mod, "is_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr(mod, "fetch_page", AsyncMock(return_value=10))
    monkeypatch.setattr(mod, "clean_page", AsyncMock(return_value=None))
    refine_mock = AsyncMock()
    monkeypatch.setattr(mod, "refine_page", refine_mock)
    monkeypatch.setattr(mod, "finish_job", AsyncMock())

    await mod.refresh_url({"session_factory": factory}, job_id=1, page_id=10)
    refine_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_url_refine_drop_skips_chunk(monkeypatch):
    page = FakePage()
    factory = _make_factory(page=page)
    monkeypatch.setattr(mod, "start_job", AsyncMock())
    monkeypatch.setattr(mod, "is_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr(mod, "fetch_page", AsyncMock(return_value=10))
    monkeypatch.setattr(
        mod,
        "clean_page",
        AsyncMock(
            return_value={
                "skipped": False,
                "page_id": 10,
                "title": "T",
                "body_text": "본문",
                "content_hash": "h",
            }
        ),
    )
    monkeypatch.setattr(mod, "refine_page", AsyncMock(return_value=None))
    chunk_mock = AsyncMock()
    monkeypatch.setattr(mod, "chunk_and_index", chunk_mock)
    monkeypatch.setattr(mod, "bump_stats", AsyncMock())
    monkeypatch.setattr(mod, "finish_job", AsyncMock())

    await mod.refresh_url({"session_factory": factory}, job_id=1, page_id=10)
    chunk_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_url_cancelled_short_circuits(monkeypatch):
    page = FakePage()
    factory = _make_factory(page=page)
    monkeypatch.setattr(mod, "start_job", AsyncMock())
    monkeypatch.setattr(mod, "is_cancelled", AsyncMock(return_value=True))
    fetch_mock = AsyncMock()
    monkeypatch.setattr(mod, "fetch_page", fetch_mock)
    finish = AsyncMock()
    monkeypatch.setattr(mod, "finish_job", finish)

    await mod.refresh_url({"session_factory": factory}, job_id=1, page_id=10)

    fetch_mock.assert_not_awaited()
    args, kwargs = finish.call_args
    assert kwargs.get("status") == "CANCELLED"
