from __future__ import annotations

from dataclasses import dataclass

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from kspo_ingest.settings import settings

# 5xx / 429 / network / timeout — 재시도. 401/400은 즉시 raise (런북 B.2.A/B.2.B).
EMBED_RETRYABLE_EXC = (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    InternalServerError,
)

# 테스트에서 monkeypatch로 단축 가능. 운영 기본값은 5회 / 1~300s 지수백오프.
RETRY_MAX_ATTEMPTS = 5
RETRY_WAIT_MIN = 1.0
RETRY_WAIT_MAX = 300.0


_client: AsyncOpenAI | None = None


def get_embed_client() -> AsyncOpenAI:
    """임베딩 전용 AsyncOpenAI 싱글톤.

    `max_retries=0`으로 OpenAI SDK 내부 재시도를 끄고 tenacity로 일원화한다
    (5xx에서 SDK가 추가 재시도 → 호출 수가 multiplicative하게 늘어나는 것 방지).
    """
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key, timeout=60.0, max_retries=0
        )
    return _client


@dataclass
class EmbedBatchResult:
    vectors: list[list[float]]
    prompt_tokens: int
    total_tokens: int


async def embed_batch(
    client: AsyncOpenAI, model: str, inputs: list[str]
) -> EmbedBatchResult:
    """OpenAI embeddings.create 호출. tenacity 5회 재시도(5xx/429/timeout/network).

    응답 vectors는 inputs와 동일 순서 보장(OpenAI API 계약).
    401/400 등 비재시도 예외는 즉시 raise.
    """
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(RETRY_MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=RETRY_WAIT_MIN, max=RETRY_WAIT_MAX),
        retry=retry_if_exception_type(EMBED_RETRYABLE_EXC),
        reraise=True,
    ):
        with attempt:
            r = await client.embeddings.create(input=inputs, model=model)
            return EmbedBatchResult(
                vectors=[d.embedding for d in r.data],
                prompt_tokens=r.usage.prompt_tokens,
                total_tokens=r.usage.total_tokens,
            )
    raise RuntimeError("unreachable — reraise=True")  # pragma: no cover
