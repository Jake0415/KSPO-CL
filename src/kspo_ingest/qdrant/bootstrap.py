from __future__ import annotations

from dataclasses import dataclass

from qdrant_client.http import models as qmodels

from kspo_ingest.observability.logger import get_logger
from kspo_ingest.qdrant.client import get_client, get_mode
from kspo_ingest.settings import settings

log = get_logger("qdrant", "bootstrap")

EXPECTED_DIM = 3072  # text-embedding-3-large

# v2.1: payload 필터 인덱싱 대상 — `metadata.tags` (도메인 삭제, 첨부 필터 등)
PAYLOAD_INDEX_FIELDS: tuple[tuple[str, qmodels.PayloadSchemaType], ...] = (
    ("metadata.tags", qmodels.PayloadSchemaType.KEYWORD),
    ("metadata.domain_host", qmodels.PayloadSchemaType.KEYWORD),
    ("metadata.is_attachment", qmodels.PayloadSchemaType.BOOL),
    ("metadata.embedding_version", qmodels.PayloadSchemaType.INTEGER),
)


@dataclass
class CollectionStatus:
    exists: bool
    dim: int | None
    points_count: int | None
    healthy: bool
    error: str | None = None
    mode: str = "self_hosted"


def _vector_size(info: qmodels.CollectionInfo) -> int | None:
    """단일 named-vector / dict 양쪽 케이스 처리."""
    cfg = info.config.params.vectors
    if isinstance(cfg, qmodels.VectorParams):
        return cfg.size
    if isinstance(cfg, dict):
        # named vectors — 첫 항목 size 반환
        for v in cfg.values():
            if isinstance(v, qmodels.VectorParams):
                return v.size
    return None


async def _create_collection() -> None:
    client = get_client()
    await client.create_collection(
        collection_name=settings.qdrant_index_name,
        vectors_config=qmodels.VectorParams(
            size=EXPECTED_DIM,
            distance=qmodels.Distance.COSINE,
            on_disk=True,
        ),
        quantization_config=qmodels.ScalarQuantization(
            scalar=qmodels.ScalarQuantizationConfig(
                type=qmodels.ScalarType.INT8,
                always_ram=True,
            )
        ),
    )
    log.bind(
        event="qdrant_collection_created",
        collection=settings.qdrant_index_name,
        dim=EXPECTED_DIM,
    ).info("collection created")


async def _ensure_payload_indexes() -> None:
    client = get_client()
    for field_name, schema in PAYLOAD_INDEX_FIELDS:
        try:
            await client.create_payload_index(
                collection_name=settings.qdrant_index_name,
                field_name=field_name,
                field_schema=schema,
            )
        except Exception as exc:  # 이미 존재하거나 외부 모드 권한 부족 시 무시
            log.bind(
                event="qdrant_payload_index_skip",
                field=field_name,
                error=type(exc).__name__,
            ).debug("payload index skipped")


async def ensure_all_collections() -> list[CollectionStatus]:
    """tilellm + kspo_knowledge + kspo_archive 3개 컬렉션 보장."""
    results: list[CollectionStatus] = []
    primary = await ensure_collection()
    results.append(primary)

    for col_name in (settings.qdrant_knowledge_collection, settings.qdrant_archive_collection):
        st = await _ensure_named_collection(col_name)
        results.append(st)
    return results


async def _ensure_named_collection(name: str) -> CollectionStatus:
    """name 컬렉션 존재 보장 (self_hosted 모드만 자동 생성)."""
    client = get_client()
    mode = get_mode()

    try:
        exists = await client.collection_exists(collection_name=name)
    except Exception as exc:
        return CollectionStatus(
            exists=False, dim=None, points_count=None, healthy=False,
            error=f"qdrant_unreachable: {type(exc).__name__}", mode=mode,
        )

    if not exists:
        if mode != "self_hosted":
            return CollectionStatus(
                exists=False, dim=None, points_count=None, healthy=False,
                error=f"collection '{name}' missing in external Qdrant", mode=mode,
            )
        await client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(
                size=EXPECTED_DIM,
                distance=qmodels.Distance.COSINE,
                on_disk=True,
            ),
            quantization_config=qmodels.ScalarQuantization(
                scalar=qmodels.ScalarQuantizationConfig(
                    type=qmodels.ScalarType.INT8,
                    always_ram=True,
                )
            ),
        )
        log.bind(
            event="qdrant_collection_created", collection=name, dim=EXPECTED_DIM
        ).info("collection created")
        return CollectionStatus(
            exists=True, dim=EXPECTED_DIM, points_count=0, healthy=True, mode=mode
        )

    info = await client.get_collection(collection_name=name)
    dim = _vector_size(info)
    points_count = getattr(info, "points_count", None) or 0
    return CollectionStatus(
        exists=True, dim=dim, points_count=points_count, healthy=dim == EXPECTED_DIM, mode=mode
    )


async def ensure_collection() -> CollectionStatus:
    """컬렉션 존재 + 차원 검증. 자체 컨테이너 모드는 자동 생성, 외부는 에러.

    Returns:
        CollectionStatus.healthy=True 이면 /readyz qdrant_dim=3072 반환.
    """
    client = get_client()
    mode = get_mode()
    name = settings.qdrant_index_name

    try:
        exists = await client.collection_exists(collection_name=name)
    except Exception as exc:
        log.bind(event="qdrant_unreachable", error=type(exc).__name__).warning(str(exc))
        return CollectionStatus(
            exists=False, dim=None, points_count=None, healthy=False,
            error=f"qdrant_unreachable: {type(exc).__name__}", mode=mode,
        )

    if not exists:
        if mode != "self_hosted":
            err = (
                f"KSPO-KB-COLLECTION-MISSING: 외부 Qdrant({settings.qdrant_url})에 "
                f"컬렉션 '{name}' 미존재 — Tiledesk 측 생성 필요"
            )
            log.bind(event="qdrant_collection_missing_external", collection=name).error(err)
            return CollectionStatus(
                exists=False, dim=None, points_count=None, healthy=False,
                error=err, mode=mode,
            )
        await _create_collection()
        await _ensure_payload_indexes()
        return CollectionStatus(
            exists=True, dim=EXPECTED_DIM, points_count=0, healthy=True, mode=mode,
        )

    info = await client.get_collection(collection_name=name)
    dim = _vector_size(info)
    points_count = getattr(info, "points_count", None) or 0
    if dim != EXPECTED_DIM:
        err = (
            f"KSPO-KB-VALIDATION-DIM: 컬렉션 '{name}' 차원={dim} (기대 {EXPECTED_DIM}). "
            f"운영 런북 A 트리거"
        )
        log.bind(
            event="qdrant_dim_mismatch",
            collection=name,
            actual=dim,
            expected=EXPECTED_DIM,
        ).error(err)
        return CollectionStatus(
            exists=True, dim=dim, points_count=points_count, healthy=False,
            error=err, mode=mode,
        )

    if mode == "self_hosted":
        await _ensure_payload_indexes()
    return CollectionStatus(
        exists=True, dim=dim, points_count=points_count, healthy=True, mode=mode,
    )
