from __future__ import annotations

import pytest

from kspo_ingest.evaluation.metrics import (
    average_precision,
    mean_average_precision,
    mrr_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


QRELS = {"doc1": 2, "doc2": 1, "doc3": 0, "doc4": 1}
RANKED = ["doc3", "doc1", "doc4", "doc2"]


def test_ndcg_at_k():
    score = ndcg_at_k(RANKED, QRELS, k=4)
    assert 0.0 < score <= 1.0


def test_mrr_at_k():
    score = mrr_at_k(RANKED, QRELS, k=4)
    assert score == pytest.approx(0.5)


def test_recall_at_k():
    score = recall_at_k(RANKED, QRELS, k=2)
    assert score == pytest.approx(1 / 3)


def test_precision_at_k():
    score = precision_at_k(RANKED, QRELS, k=2)
    assert score == pytest.approx(0.5)


def test_average_precision():
    score = average_precision(RANKED, QRELS)
    assert 0.0 < score <= 1.0


def test_mean_average_precision():
    all_ranked = {"q1": RANKED, "q2": ["doc1", "doc2"]}
    all_qrels = {"q1": QRELS, "q2": {"doc1": 1, "doc2": 0}}
    score = mean_average_precision(all_ranked, all_qrels)
    assert 0.0 < score <= 1.0


def test_empty_inputs():
    assert ndcg_at_k([], {}, k=5) == 0.0
    assert mrr_at_k([], {}, k=5) == 0.0
    assert recall_at_k([], {}, k=5) == 0.0
    assert precision_at_k([], {}, k=5) == 0.0
    assert mean_average_precision({}, {}) == 0.0
