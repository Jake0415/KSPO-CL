from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from kspo_ingest.settings import settings

# 5xx/429/network — 재시도. 401/400은 즉시 raise (런북 B.2.A/B.2.B).
RETRYABLE_EXC = (APIConnectionError, APITimeoutError, RateLimitError)

_client: AsyncOpenAI | None = None

T = TypeVar("T")


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=60.0)
    return _client


async def call_with_retry(coro_factory: Callable[[], Awaitable[T]]) -> T:  # noqa: UP047
    """tenacity 5회 + 지수 백오프, 재시도 가능 예외만."""
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=300),
        retry=retry_if_exception_type(RETRYABLE_EXC),
        reraise=True,
    ):
        with attempt:
            return await coro_factory()
    raise RuntimeError("unreachable — reraise=True")  # pragma: no cover
