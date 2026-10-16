"""Embedding policy — Quadrant별 임베딩 대상 컬렉션 결정.

Quadrant 분류 ≠ Embedding 결정 분리 원칙.
Q1: 고품질 → 챗봇(QDRANT_INDEX_NAME) + 내부 지식(kspo_knowledge)
Q2/Q3: 유효 콘텐츠 → 내부 지식만
Q4: 임베딩 안 함 (비용 절약)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from kspo_ingest.crawl.url_class import is_landing_hub
from kspo_ingest.quality.scorer import ScoreResult
from kspo_ingest.settings import settings


@dataclass(frozen=True)
class EmbeddingPolicy:
    """Quadrant → target collection 매핑.

    챗봇 컬렉션은 settings.qdrant_index_name(.env의 QDRANT_INDEX_NAME)으로 결정된다.
    """

    q1: list[str] = field(default_factory=lambda: [settings.qdrant_index_name, "kspo_knowledge"])
    q2: list[str] = field(default_factory=lambda: ["kspo_knowledge"])
    q3: list[str] = field(default_factory=lambda: ["kspo_knowledge"])
    q4: list[str] = field(default_factory=list)


DEFAULT_POLICY = EmbeddingPolicy()


def resolve_embedding_targets(
    score: ScoreResult,
    policy: EmbeddingPolicy | None = None,
    *,
    url: str | None = None,
) -> list[str]:
    """ScoreResult의 quadrant에 따라 upsert 대상 컬렉션 목록 반환.

    url이 랜딩 허브면 quadrant와 무관하게 [] 반환 — doc_quality 기록만 하고
    chunk/embed/Qdrant publish는 스킵한다. 순수 함수 — 상태 없음, I/O 없음.
    """
    if (
        url
        and urlsplit(url).hostname == "soma.kspo.or.kr"
        and re.fullmatch(r"/piece/product/\d+/pop", urlsplit(url).path)
    ):
        return list((policy or DEFAULT_POLICY).q1)
    if url and is_landing_hub(url):
        return []
    if policy is None:
        policy = DEFAULT_POLICY

    mapping = {
        "Q1": policy.q1,
        "Q2": policy.q2,
        "Q3": policy.q3,
        "Q4": policy.q4,
    }
    return list(mapping.get(score.quadrant, policy.q4))
