from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_P = "kspo_ingest.tasks.pipeline.enqueue_seeds"


@pytest.mark.asyncio
async def test_enqueue_seeds_uses_frontier():
    """BFS loop should seed root URL and dequeue until frontier is empty."""
    from kspo_ingest.tasks.pipeline.enqueue_seeds import enqueue_seeds

    # Mock session factory
    mock_domain = MagicMock()
    mock_domain.host = "www.kspo.or.kr"
    mock_domain.scheme = "https"
    mock_domain.max_pages = 100
    mock_domain.max_depth = 5

    mock_page = MagicMock()
    mock_page.posted_at = None

    from kspo_ingest.db.models import Domain, Page

    async def _session_get(model, pk):
        if model is Page:
            return mock_page
        return mock_domain

    session = AsyncMock()
    session.get = _session_get

    session_ctx = AsyncMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)

    session_factory = MagicMock(return_value=session_ctx)

    # Mock frontier: returns root URL once, then None (empty)
    frontier = AsyncMock()
    frontier.enqueue = AsyncMock(return_value=True)
    frontier.dequeue = AsyncMock(side_effect=[
        ("https://www.kspo.or.kr/", 0),
        None,  # frontier empty
    ])
    frontier.ack = AsyncMock()

    ctx = {
        "session_factory": session_factory,
        "frontier": frontier,
        "redis": AsyncMock(),
        "fetcher": AsyncMock(),
        "robots": AsyncMock(),
        "rate_limit": AsyncMock(),
        "storage_root": MagicMock(),
    }

    clean_rv = {"title": "T", "body_text": "B", "content_hash": "h"}
    refine_rv = {
        "refined": {
            "refined_text": "R", "summary": "S", "keywords": [],
        },
    }

    with (
        patch(f"{_P}.start_job", new_callable=AsyncMock),
        patch(f"{_P}.finish_job", new_callable=AsyncMock),
        patch(f"{_P}.bump_stats", new_callable=AsyncMock),
        patch(
            f"{_P}.is_cancelled",
            new_callable=AsyncMock, return_value=False,
        ),
        patch(
            f"{_P}.fetch_page",
            new_callable=AsyncMock, return_value=1,
        ),
        patch(
            f"{_P}.clean_page",
            new_callable=AsyncMock, return_value=clean_rv,
        ),
        patch(
            f"{_P}.extract_links",
            new_callable=AsyncMock,
            return_value={"attachments": 0, "discovered": 0},
        ),
        patch(
            f"{_P}.refine_page",
            new_callable=AsyncMock, return_value=refine_rv,
        ),
        patch(f"{_P}.chunk_and_index", new_callable=AsyncMock),
        patch(
            f"{_P}.is_budget_exceeded",
            new_callable=AsyncMock, return_value=False,
        ),
        patch(
            f"{_P}._enqueue_discovered",
            new_callable=AsyncMock, return_value=0,
        ),
    ):
        await enqueue_seeds(ctx, job_id=1, domain_id=1)

    # Frontier should have been seeded with root URL
    frontier.enqueue.assert_called_with(
        1, "https://www.kspo.or.kr/", depth=0,
    )
    # Should have dequeued at least once
    assert frontier.dequeue.call_count >= 1
    # Should have acked the processed URL
    frontier.ack.assert_called()
