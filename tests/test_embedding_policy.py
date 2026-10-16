"""Embedding policy 단위 테스트 — resolve_embedding_targets + EmbeddingPolicy."""
from __future__ import annotations

import pytest

from kspo_ingest.quality.embedding_policy import (
    DEFAULT_POLICY,
    EmbeddingPolicy,
    resolve_embedding_targets,
)
from kspo_ingest.quality.scorer import ScoreResult


def _make_score(quadrant: str) -> ScoreResult:
    return ScoreResult(
        quality_score=0.8,
        structure_score=0.7,
        freshness_score=0.9,
        trust_score=1.0,
        duplicate_score=1.0,
        simhash_value=0,
        quadrant=quadrant,
        extraction_method="main_article",
        body_length=1000,
        korean_ratio=0.6,
        has_title=True,
        has_posted_at=True,
        has_summary=True,
        keyword_count=5,
    )


class TestResolveEmbeddingTargets:
    def test_q1_returns_both_collections(self):
        targets = resolve_embedding_targets(_make_score("Q1"))
        assert targets == ["tilellm", "kspo_knowledge"]

    def test_q2_returns_knowledge_only(self):
        targets = resolve_embedding_targets(_make_score("Q2"))
        assert targets == ["kspo_knowledge"]

    def test_q3_returns_knowledge_only(self):
        targets = resolve_embedding_targets(_make_score("Q3"))
        assert targets == ["kspo_knowledge"]

    def test_q4_returns_empty(self):
        targets = resolve_embedding_targets(_make_score("Q4"))
        assert targets == []

    def test_unknown_quadrant_returns_empty(self):
        targets = resolve_embedding_targets(_make_score("Q99"))
        assert targets == []

    def test_custom_policy(self):
        policy = EmbeddingPolicy(
            q1=["custom_primary"],
            q2=["custom_secondary"],
            q3=[],
            q4=[],
        )
        assert resolve_embedding_targets(_make_score("Q1"), policy) == ["custom_primary"]
        assert resolve_embedding_targets(_make_score("Q2"), policy) == ["custom_secondary"]
        assert resolve_embedding_targets(_make_score("Q3"), policy) == []

    def test_default_policy_is_frozen(self):
        with pytest.raises(AttributeError):
            DEFAULT_POLICY.q1 = ["other"]  # type: ignore[misc]

    def test_returns_copy_not_reference(self):
        """반환값 수정이 policy에 영향 없음."""
        targets = resolve_embedding_targets(_make_score("Q1"))
        targets.append("extra")
        assert resolve_embedding_targets(_make_score("Q1")) == ["tilellm", "kspo_knowledge"]
