from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from openai import AsyncOpenAI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.db.models import Chunk as ChunkRow
from kspo_ingest.db.models import LlmUsage
from kspo_ingest.embed.cost import calc_embed_cost_usd
from kspo_ingest.embed.openai_embed import embed_batch, get_embed_client
from kspo_ingest.observability.logger import get_logger

log = get_logger("embed", "embedder")

BATCH_SIZE = 96  # docs/design/03_chunk_embed_qdrant.md §3.5


@dataclass
class ChunkToEmbed:
    chunk_id: int
    text: str


@dataclass
class EmbeddedChunk:
    chunk_id: int
    vector: list[float]


@dataclass
class EmbedResult:
    embedded: list[EmbeddedChunk] = field(default_factory=list)
    success_chunk_ids: list[int] = field(default_factory=list)
    error_chunk_ids: list[int] = field(default_factory=list)
    total_prompt_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")


async def _embed_one_with_fallback(
    client: AsyncOpenAI,
    model: str,
    items: list[ChunkToEmbed],
    *,
    embedded: list[EmbeddedChunk],
    success_ids: list[int],
    error_ids: list[int],
) -> int:
    """배치 실패 후 단건씩 재시도. 누계 prompt_tokens 반환."""
    total = 0
    for item in items:
        try:
            rs = await embed_batch(client, model, [item.text])
        except Exception as exc:  # noqa: BLE001
            log.bind(
                event="embed_chunk_error",
                chunk_id=item.chunk_id,
                error=type(exc).__name__,
            ).warning("single chunk embed failed")
            error_ids.append(item.chunk_id)
            continue
        embedded.append(EmbeddedChunk(chunk_id=item.chunk_id, vector=rs.vectors[0]))
        success_ids.append(item.chunk_id)
        total += rs.prompt_tokens
    return total


async def embed_chunks(
    session: AsyncSession | None,
    items: list[ChunkToEmbed],
    *,
    model: str,
    job_id: int | None,
    client: AsyncOpenAI | None = None,
    batch_size: int = BATCH_SIZE,
) -> EmbedResult:
    """청크 텍스트 배치 임베딩.

    1) `batch_size`(96) 단위로 호출
    2) 배치 호출 실패 시 1건씩 재호출 (fallback)
    3) `session` 있으면 PG `chunks.embed_status` / `embedding_model` + `llm_usage` 1행 누계 기록
    4) 벡터는 PG에 저장 안 함 — Qdrant upsert(T3.3)에서 사용

    Returns:
      EmbedResult — `embedded`(성공 청크+벡터), `error_chunk_ids`, 누계 prompt/cost.
    """
    result = EmbedResult()
    if not items:
        return result

    if client is None:
        client = get_embed_client()

    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        try:
            r = await embed_batch(client, model, [c.text for c in batch])
        except Exception as exc:  # noqa: BLE001
            log.bind(
                event="embed_batch_failed",
                size=len(batch),
                error=type(exc).__name__,
            ).warning("batch failed — falling back to singles")
            result.total_prompt_tokens += await _embed_one_with_fallback(
                client,
                model,
                batch,
                embedded=result.embedded,
                success_ids=result.success_chunk_ids,
                error_ids=result.error_chunk_ids,
            )
            continue

        for item, vec in zip(batch, r.vectors, strict=True):
            result.embedded.append(EmbeddedChunk(chunk_id=item.chunk_id, vector=vec))
            result.success_chunk_ids.append(item.chunk_id)
        result.total_prompt_tokens += r.prompt_tokens
        log.bind(
            event="embed_batch_ok",
            size=len(batch),
            prompt=r.prompt_tokens,
        ).info("batch ok")

    result.total_cost_usd = calc_embed_cost_usd(model, result.total_prompt_tokens)

    if session is not None:
        await _persist_results(
            session,
            model=model,
            job_id=job_id,
            success_ids=result.success_chunk_ids,
            error_ids=result.error_chunk_ids,
            total_prompt_tokens=result.total_prompt_tokens,
            total_cost_usd=result.total_cost_usd,
        )

    return result


async def _persist_results(
    session: AsyncSession,
    *,
    model: str,
    job_id: int | None,
    success_ids: list[int],
    error_ids: list[int],
    total_prompt_tokens: int,
    total_cost_usd: Decimal,
) -> None:
    """PG `chunks` 상태 갱신 + `llm_usage` 1행 누계 기록 (호출 단위)."""
    if success_ids:
        await session.execute(
            update(ChunkRow)
            .where(ChunkRow.id.in_(success_ids))
            .values(embed_status="OK", embedding_model=model)
        )
    if error_ids:
        await session.execute(
            update(ChunkRow)
            .where(ChunkRow.id.in_(error_ids))
            .values(embed_status="ERROR")
        )
    if total_prompt_tokens > 0:
        session.add(
            LlmUsage(
                page_id=None,
                attachment_id=None,
                job_id=job_id,
                purpose="embedding",
                model=model,
                prompt_tokens=total_prompt_tokens,
                completion_tokens=0,
                total_tokens=total_prompt_tokens,
                cost_usd=total_cost_usd,
            )
        )
    await session.commit()
