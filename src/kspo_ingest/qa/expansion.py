"""Domain-vocabulary query expansion for retrieval recall.

Short queries using a colloquial/synonym term embed away from the corpus's
canonical vocabulary, so dense search misses the answer chunk even though it
exists. Measured examples:

  - "체육진흥공단 대표자"  → answer chunk (조현재 이사장) absent from top-10;
    "체육진흥공단 대표자 이사장" → rank 1.
  - "스포츠토토는 어떤 사업이야" → only 신고센터 pages; the business is described
    under the official term "체육진흥투표권" → surfaced once that term is added.

We append the canonical term(s) to the EMBEDDING query only — the LLM still sees
the original question, so answers stay natural and grounded. Kept small and
precise: over-expansion dilutes the query vector (four synonyms pushed the same
answer from rank 1 to rank 8), and triggers are whole domain terms (never a bare
substring like "대표", which must not fire on "대표전화"/"대표번호").
"""
from __future__ import annotations

# trigger term (as it appears in a user query) → canonical corpus term(s) to add
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "대표자": ("이사장",),
    "대표이사": ("이사장",),
    "기관장": ("이사장",),
    "최고경영자": ("이사장",),
    "스포츠토토": ("체육진흥투표권",),
    "토토": ("체육진흥투표권",),
    "복권": ("체육진흥투표권",),
    # 부서/조직 어휘 — 코퍼스의 canonical 페이지는 "조직도/직원안내/조직안내"로 표기.
    "부서": ("조직도", "직원안내"),
    "부서안내": ("조직도", "직원안내"),
}


def expand_query(question: str) -> str:
    """Return the question augmented with canonical synonyms for embedding.

    Returns the original string unchanged when no trigger matches (no dilution
    for queries that already use canonical vocabulary).
    """
    q = question or ""
    extra: list[str] = []
    for term, adds in _SYNONYMS.items():
        if term in q:
            for a in adds:
                if a not in q and a not in extra:
                    extra.append(a)
    if not extra:
        return question
    return f"{question} {' '.join(extra)}"
