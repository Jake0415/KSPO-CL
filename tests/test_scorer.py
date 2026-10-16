"""Tests for quality.scorer — 문서 품질 + 구조화 점수 + Quadrant 배정."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kspo_ingest.quality.scorer import (
    ScorerInput,
    _assign_quadrant,
    _compute_freshness,
    _domain_trust,
    _weighted_avg,
    score_document,
)


class TestWeightedAvg:
    def test_basic(self):
        result = _weighted_avg([(1.0, 1.0), (0.0, 1.0)])
        assert result == pytest.approx(0.5)

    def test_weighted(self):
        result = _weighted_avg([(1.0, 3.0), (0.0, 1.0)])
        assert result == pytest.approx(0.75)

    def test_empty(self):
        assert _weighted_avg([]) == 0.0


class TestFreshness:
    def test_recent(self):
        posted = datetime.now(UTC) - timedelta(days=30)
        assert _compute_freshness(posted) == 1.0

    def test_3_months(self):
        posted = datetime.now(UTC) - timedelta(days=90)
        assert _compute_freshness(posted) == 1.0

    def test_6_months(self):
        posted = datetime.now(UTC) - timedelta(days=180)
        score = _compute_freshness(posted)
        assert 0.7 < score < 1.0

    def test_2_years(self):
        posted = datetime.now(UTC) - timedelta(days=730)
        score = _compute_freshness(posted)
        assert 0.5 < score < 0.8

    def test_10_years(self):
        posted = datetime.now(UTC) - timedelta(days=3650)
        score = _compute_freshness(posted)
        assert score == pytest.approx(0.1)  # floor

    def test_none(self):
        assert _compute_freshness(None) == 0.5

    def test_future(self):
        posted = datetime.now(UTC) + timedelta(days=30)
        assert _compute_freshness(posted) == 1.0


class TestDomainTrust:
    def test_kspo(self):
        assert _domain_trust("www.kspo.or.kr") == 1.0

    def test_nfa(self):
        assert _domain_trust("nfa.kspo.or.kr") == 1.0

    def test_external(self):
        assert _domain_trust("example.com") == 0.7


class TestAssignQuadrant:
    def test_q1_high_both(self):
        assert _assign_quadrant(0.8, 0.8) == "Q1"

    def test_q2_high_quality_low_structure(self):
        assert _assign_quadrant(0.8, 0.3) == "Q2"

    def test_q3_low_quality_mid_structure(self):
        assert _assign_quadrant(0.4, 0.5) == "Q3"

    def test_q4_low_both(self):
        assert _assign_quadrant(0.3, 0.2) == "Q4"

    def test_boundary_q1(self):
        assert _assign_quadrant(0.6, 0.6) == "Q1"

    def test_boundary_q3(self):
        assert _assign_quadrant(0.59, 0.4) == "Q3"


class TestScoreDocument:
    def _make_input(self, **overrides) -> ScorerInput:
        defaults = {
            "title": "공지사항 제목",
            "body_text": "한국체육진흥공단에서 알려드립니다. " * 50,
            "extraction_method": "main_article",
            "posted_at": datetime.now(UTC) - timedelta(days=30),
            "summary": "공단 관련 공지사항 요약입니다.",
            "keywords": ["체육", "공지", "진흥공단"],
            "is_meaningful": True,
            "domain_host": "www.kspo.or.kr",
        }
        defaults.update(overrides)
        return ScorerInput(**defaults)

    def test_high_quality_document(self):
        score = score_document(self._make_input())
        assert score.quality_score >= 0.6
        assert score.structure_score >= 0.6
        assert score.quadrant == "Q1"
        assert score.has_title is True
        assert score.has_summary is True

    def test_short_body_lower_quality(self):
        short = score_document(self._make_input(body_text="짧은 본문"))
        full = score_document(self._make_input())
        assert short.quality_score < full.quality_score
        assert short.body_length == 5

    def test_no_title_lower_structure(self):
        score = score_document(self._make_input(title=None))
        assert score.has_title is False
        # structure_score should be lower without title

    def test_no_metadata_q2(self):
        score = score_document(
            self._make_input(
                title=None,
                posted_at=None,
                summary=None,
                keywords=[],
            )
        )
        # quality might still be ok (body + extraction + korean), but structure low
        assert score.structure_score < 0.6

    def test_not_meaningful_drops_quality(self):
        score = score_document(self._make_input(is_meaningful=False))
        # is_meaningful has weight 2.0 in quality
        assert score.quality_score < score_document(self._make_input()).quality_score

    def test_heuristic_extraction_lower(self):
        score = score_document(self._make_input(extraction_method="heuristic"))
        baseline = score_document(self._make_input(extraction_method="main_article"))
        assert score.quality_score < baseline.quality_score

    def test_korean_ratio(self):
        score = score_document(
            self._make_input(
                body_text="한국체육진흥공단에서 알려드립니다. " * 50,
            )
        )
        assert score.korean_ratio > 0.5

    def test_english_body_low_korean(self):
        score = score_document(
            self._make_input(
                body_text="This is an English document without Korean characters. " * 50,
            )
        )
        assert score.korean_ratio < 0.1

    def test_scorer_version(self):
        from kspo_ingest.quality.scorer import SCORER_VERSION

        assert SCORER_VERSION >= 1


class TestShouldPublish:
    def test_q1_publishes(self):
        from kspo_ingest.quality.gate import should_publish
        from kspo_ingest.quality.scorer import ScoreResult

        score = ScoreResult(
            quality_score=0.8,
            structure_score=0.8,
            freshness_score=0.9,
            trust_score=1.0,
            duplicate_score=1.0,
            simhash_value=0,
            quadrant="Q1",
            extraction_method="main_article",
            body_length=1000,
            korean_ratio=0.8,
            has_title=True,
            has_posted_at=True,
            has_summary=True,
            keyword_count=5,
        )
        assert should_publish(score) is True

    def test_q2_skips(self):
        from kspo_ingest.quality.gate import should_publish
        from kspo_ingest.quality.scorer import ScoreResult

        score = ScoreResult(
            quality_score=0.8,
            structure_score=0.3,
            freshness_score=0.9,
            trust_score=1.0,
            duplicate_score=1.0,
            simhash_value=0,
            quadrant="Q2",
            extraction_method="main_article",
            body_length=1000,
            korean_ratio=0.8,
            has_title=True,
            has_posted_at=True,
            has_summary=False,
            keyword_count=0,
        )
        assert should_publish(score) is False

    def test_low_freshness_skips(self):
        from kspo_ingest.quality.gate import should_publish
        from kspo_ingest.quality.scorer import ScoreResult

        score = ScoreResult(
            quality_score=0.8,
            structure_score=0.8,
            freshness_score=0.2,
            trust_score=1.0,
            duplicate_score=1.0,
            simhash_value=0,
            quadrant="Q1",
            extraction_method="main_article",
            body_length=1000,
            korean_ratio=0.8,
            has_title=True,
            has_posted_at=True,
            has_summary=True,
            keyword_count=5,
        )
        assert should_publish(score) is False

    def test_duplicate_skips(self):
        from kspo_ingest.quality.gate import should_publish
        from kspo_ingest.quality.scorer import ScoreResult

        score = ScoreResult(
            quality_score=0.8,
            structure_score=0.8,
            freshness_score=0.9,
            trust_score=1.0,
            duplicate_score=0.3,
            simhash_value=0,
            quadrant="Q1",
            extraction_method="main_article",
            body_length=1000,
            korean_ratio=0.8,
            has_title=True,
            has_posted_at=True,
            has_summary=True,
            keyword_count=5,
        )
        assert should_publish(score) is False


def test_language_ratio_does_not_reduce_quality():
    from kspo_ingest.quality.scorer import ScorerInput, score_document

    common = {
        "title": "Artwork",
        "extraction_method": "main_article",
        "posted_at": None,
        "summary": "Artwork details",
        "keywords": ["art"],
        "is_meaningful": True,
        "domain_host": "soma.kspo.or.kr",
    }
    korean = score_document(ScorerInput(body_text="가" * 600, **common))
    english = score_document(ScorerInput(body_text="a" * 600, **common))
    assert korean.quality_score == english.quality_score
    assert korean.quadrant == english.quadrant
    assert korean.korean_ratio != english.korean_ratio
