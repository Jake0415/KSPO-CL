"""Pure IR metric functions.

Ported from bari-chatbot/evaluation/metrics.py.
All functions take (ranked_doc_ids, qrels, k) and return a float.
No external dependencies. No side effects.

qrels format: dict[str, int] mapping doc_id -> relevance grade (0/1/2).
Docs not in qrels are assumed relevance 0.
"""
from __future__ import annotations

import math


def ndcg_at_k(ranked_ids: list[str], qrels: dict[str, int], k: int) -> float:
    if not ranked_ids or not qrels:
        return 0.0
    dcg = _dcg(ranked_ids[:k], qrels)
    ideal_ids = sorted(qrels, key=lambda d: qrels[d], reverse=True)[:k]
    idcg = _dcg(ideal_ids, qrels)
    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def _dcg(ranked_ids: list[str], qrels: dict[str, int]) -> float:
    total = 0.0
    for i, doc_id in enumerate(ranked_ids):
        rel = qrels.get(doc_id, 0)
        gain = (2**rel) - 1
        total += gain / math.log2(i + 2)
    return total


def mrr_at_k(ranked_ids: list[str], qrels: dict[str, int], k: int) -> float:
    for i, doc_id in enumerate(ranked_ids[:k]):
        if qrels.get(doc_id, 0) >= 1:
            return 1.0 / (i + 1)
    return 0.0


def recall_at_k(ranked_ids: list[str], qrels: dict[str, int], k: int) -> float:
    relevant = {d for d, r in qrels.items() if r >= 1}
    if not relevant:
        return 0.0
    retrieved_relevant = relevant & set(ranked_ids[:k])
    return len(retrieved_relevant) / len(relevant)


def precision_at_k(ranked_ids: list[str], qrels: dict[str, int], k: int) -> float:
    if not ranked_ids:
        return 0.0
    top_k = ranked_ids[:k]
    relevant_count = sum(1 for d in top_k if qrels.get(d, 0) >= 1)
    return relevant_count / len(top_k)


def average_precision(ranked_ids: list[str], qrels: dict[str, int]) -> float:
    relevant = {d for d, r in qrels.items() if r >= 1}
    if not relevant:
        return 0.0
    hits = 0
    sum_precision = 0.0
    for i, doc_id in enumerate(ranked_ids):
        if doc_id in relevant:
            hits += 1
            sum_precision += hits / (i + 1)
    return sum_precision / len(relevant)


def mean_average_precision(
    all_ranked: dict[str, list[str]],
    all_qrels: dict[str, dict[str, int]],
) -> float:
    if not all_ranked:
        return 0.0
    total = sum(
        average_precision(all_ranked[qid], all_qrels.get(qid, {}))
        for qid in all_ranked
    )
    return total / len(all_ranked)
