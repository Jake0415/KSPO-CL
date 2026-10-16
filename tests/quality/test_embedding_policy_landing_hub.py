from __future__ import annotations

from kspo_ingest.quality.embedding_policy import resolve_embedding_targets
from kspo_ingest.quality.scorer import ScoreResult


def _q1() -> ScoreResult:
    # Q1 = 최고 품질(원래라면 tilellm+kspo_knowledge 둘 다 적재)
    return ScoreResult(
        quality_score=0.9,
        structure_score=0.8,
        freshness_score=0.9,
        trust_score=0.9,
        duplicate_score=1.0,
        simhash_value=0,
        quadrant="Q1",
        extraction_method="main_article",
        body_length=1000,
        korean_ratio=0.6,
        has_title=True,
        has_posted_at=True,
        has_summary=True,
        keyword_count=5,
    )


def test_landing_hub_url_returns_no_targets():
    assert resolve_embedding_targets(_q1(), url="https://x.kr/news/main/main.do") == []


def test_content_url_keeps_q1_targets():
    assert resolve_embedding_targets(
        _q1(), url="https://x.kr/news/bbs/B1/view.do?nttId=1"
    ) == ["tilellm", "kspo_knowledge"]


def test_url_none_is_backward_compatible():
    assert resolve_embedding_targets(_q1()) == ["tilellm", "kspo_knowledge"]
