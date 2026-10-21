"""Bounded post-processing: collection continues while refinement/publishing runs.

Tasks are owned by the parent job, drained before completion, and cancelled on
failure. Cleaned source/checkpoint files remain on disk for a later retry.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from redis.asyncio import Redis
from redis.exceptions import LockNotOwnedError

from kspo_ingest.db.models import Page
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.settings import settings
from kspo_ingest.tasks.jobs import bump_stats, is_cancelled
from kspo_ingest.tasks.pipeline.helpers import mark_error

log = get_logger("worker", "parallel")
Work = Callable[[], Awaitable[bool | None]]


class PublicationError(RuntimeError):
    def __init__(self, message: str, *, counted: bool = False):
        super().__init__(message)
        self.counted = counted


class PostprocessPool:
    def __init__(self, ctx: dict, job_id: int, slots: asyncio.Semaphore, limit: int):
        self.ctx, self.job_id, self.slots = ctx, job_id, slots
        self.limit = limit
        self.tasks: set[asyncio.Task] = set()
        self.seen: set[int] = set()

    async def stats(self, **delta):
        async with self.ctx["session_factory"]() as session:
            await bump_stats(session, self.job_id, **delta)

    async def submit(self, page_id: int, work: Work):
        if page_id in self.seen:
            return
        while len(self.tasks) >= self.limit:
            done, self.tasks = await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
            await asyncio.gather(*done)
        self.seen.add(page_id)
        await self.stats(processing_submitted=1, processing_pending=1)
        task = asyncio.create_task(self.run(page_id, work))
        self.tasks.add(task)

    async def run(self, page_id: int, work: Work):
        started = time.monotonic()
        running = False
        try:
            async with self.slots:
                async with self.ctx["session_factory"]() as session:
                    if await is_cancelled(session, self.job_id):
                        return
                await self.stats(processing_running=1)
                running = True
                completed = await work()
                if completed is False:
                    await self.stats(processing_deferred=1)
                    return
                async with self.ctx["session_factory"]() as session:
                    if await is_cancelled(session, self.job_id):
                        return
                    page = await session.get(Page, page_id)
                    if page is not None:
                        page.storage_paths = {
                            **(page.storage_paths or {}),
                            "processing_pending": False,
                        }
                        await session.commit()
                await self.stats(processing_completed=1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.bind(
                event="postprocess_error",
                job_id=self.job_id,
                page_id=page_id,
                error=type(exc).__name__,
            ).warning("post-processing failed")
            async with self.ctx["session_factory"]() as session:
                await mark_error(session, page_id, error=str(exc)[:500])
                await bump_stats(
                    session,
                    self.job_id,
                    errors=int(not getattr(exc, "counted", False)),
                    processing_failed=1,
                )
        finally:
            await self.stats(processing_pending=-1, processing_running=-int(running))
            log.bind(
                event="postprocess_done",
                job_id=self.job_id,
                page_id=page_id,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            ).info("post-processing settled")

    async def drain(self):
        while self.tasks:
            tasks = set(self.tasks)
            try:
                await asyncio.gather(*tasks)
            except BaseException:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self.tasks.difference_update(tasks)
                raise
            self.tasks.difference_update(tasks)

    async def cancel(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()


@asynccontextmanager
async def processing_scope(ctx: dict, job_id: int, domain_id: int | None = None):
    if isinstance(ctx.get("postprocess_pool"), PostprocessPool):
        yield ctx
        return
    limit = settings.postprocess_concurrency
    slots = ctx.setdefault("postprocess_slots", asyncio.BoundedSemaphore(limit))
    pool = PostprocessPool(ctx, job_id, slots, limit)
    lock = None
    redis = ctx.get("redis")
    # Whole-site resets must never overlap outstanding post-processing of the same site.
    if domain_id is not None and isinstance(redis, Redis):
        lock = redis.lock(f"kspo:collection_domain:{domain_id}", timeout=21720, blocking_timeout=0)
        if not await lock.acquire(blocking=False):
            raise RuntimeError("Another collection is active for this domain")
    try:
        yield {**ctx, "postprocess_pool": pool}
        await pool.drain()
    except BaseException:
        await pool.cancel()
        raise
    finally:
        if lock is not None:
            try:
                await lock.release()
            except LockNotOwnedError:
                # Never delete a newer owner's lock or overwrite a completed crawl.
                log.bind(event="collection_lock_expired", job_id=job_id,
                         domain_id=domain_id).warning("collection finished after lock expiry")


async def submit_postprocessing(ctx: dict, job_id: int, page_id: int, work: Work):
    pool = ctx.get("postprocess_pool")
    if isinstance(pool, PostprocessPool):
        await pool.submit(page_id, work)
    else:
        # Direct per-page callers retain synchronous completion semantics.
        slots = ctx.setdefault(
            "postprocess_slots", asyncio.BoundedSemaphore(settings.postprocess_concurrency)
        )
        async with slots:
            await work()


async def drain_processing(ctx: dict):
    pool = ctx.get("postprocess_pool")
    if isinstance(pool, PostprocessPool):
        await pool.drain()
