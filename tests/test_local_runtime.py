from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from kspo_ingest import local_worker


def local_settings(**overrides):
    values = {
        "app_env": "local",
        "qdrant_url": "http://qdrant:6333",
        "postgres_host": "postgres",
        "redis_url": "redis://redis:6379/0",
        "sonar_base_url": "",
        "sonar_project_id": "",
        "sonar_email": "",
        "sonar_password": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_manual_worker_keeps_cron_disabled_and_enables_local_indexing(monkeypatch):
    monkeypatch.setattr(local_worker, "settings", local_settings())
    ctx = {}
    with patch.object(local_worker, "base_startup", new=AsyncMock()) as startup:
        await local_worker.on_startup(ctx)
    startup.assert_awaited_once_with(ctx)
    assert ctx["local_direct_indexing"]
    assert local_worker.WorkerSettings.cron_jobs == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"qdrant_url": "http://production:6333"},
        {"postgres_host": "production"},
        {"redis_url": "redis://production:6379/0"},
        {"sonar_base_url": "http://production:8081"},
        {"app_env": "production"},
    ],
)
async def test_worker_rejects_external_storage(monkeypatch, overrides):
    monkeypatch.setattr(local_worker, "settings", local_settings(**overrides))
    with (
        patch.object(local_worker, "base_startup", new=AsyncMock()) as startup,
        pytest.raises(RuntimeError),
    ):
        await local_worker.on_startup({})
    startup.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_push_uses_existing_direct_indexer():
    from kspo_ingest.tasks.pipeline.push_to_sonar import push_to_sonar

    ctx = {"local_direct_indexing": True, "session_factory": None}
    with patch(
        "kspo_ingest.tasks.pipeline.chunk_and_index.chunk_and_index", new=AsyncMock(return_value=2)
    ) as index:
        result = await push_to_sonar(
            ctx,
            job_id=1,
            page_id=2,
            refined_text="public text",
            summary="summary",
            keywords=["word"],
        )
    assert result == 1
    index.assert_awaited_once_with(
        ctx, job_id=1, page_id=2, refined_text="public text", summary="summary", keywords=["word"]
    )


def test_arq_discovers_local_functions_without_inherited_settings():
    from arq.worker import get_kwargs

    kwargs = get_kwargs(local_worker.WorkerSettings)
    assert len(kwargs["functions"]) > 0
    assert kwargs["cron_jobs"] == []
    assert kwargs["redis_settings"] == local_worker.BaseWorkerSettings.redis_settings
