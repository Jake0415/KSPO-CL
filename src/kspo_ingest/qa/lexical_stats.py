"""Corpus document-frequency stats for IDF-weighted lexical reranking.

Root cause this addresses: the ingest corpus prefixes every chunk with a header
containing the org name, so a query like ``체육진흥공단 인재상`` has one ubiquitous
term (체육진흥공단, in ~all docs) and one discriminative term (인재상, in a handful).
Unweighted lexical overlap counts both equally, so the org name dominates and the
exact-term page is under-ranked below generic chunks that merely share it. IDF
weighting fixes this generally: a term's weight is ``log(N/df)`` so ubiquitous
boilerplate terms contribute ~0 and rare, meaningful terms carry the signal — used
by ``retrieval.lexical_overlap`` to rerank the dense pool (fixes e.g. 인재상 at
dense rank ~20, inside the pool).

Broader lexical fixes (a candidate path for pages dense misses ENTIRELY, and
re-embedding on org-name-stripped text) were both evaluated and REJECTED by
full-suite regression — see the notes in ``api/routers/qa.py`` and
``tasks/pipeline/chunk_and_index.py``. So this module only supplies IDF.

The df map is built once from the live collection (a pure scroll, no embeddings)
and cached with a TTL, since the corpus changes only on (re-)ingest.
"""
from __future__ import annotations

import math
import time
from collections import Counter

from kspo_ingest.observability.logger import get_logger
from kspo_ingest.qa.retrieval import _tokens

log = get_logger("qa", "lexical_stats")

_TTL_SECONDS = 600
_cache: dict | None = None  # {"idf": {term: float}, "built_at": float}


async def _build() -> dict:
    from kspo_ingest.qdrant.client import get_client
    from kspo_ingest.settings import settings

    client = get_client()
    df: Counter[str] = Counter()
    n_docs = 0
    offset = None
    while True:
        points, offset = await client.scroll(
            collection_name=settings.qdrant_index_name,
            limit=1000,
            offset=offset,
            with_payload=["page_content"],
            with_vectors=False,
        )
        for p in points:
            body = (p.payload or {}).get("page_content", "")
            n_docs += 1
            for term in _tokens(body):  # set() per doc → document frequency
                df[term] += 1
        if offset is None:
            break
    n = max(n_docs, 1)
    idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
    log.bind(event="lexical_idf_built", docs=n, vocab=len(idf)).info("idf built")
    return {"idf": idf}


async def get_idf(*, now: float | None = None) -> dict[str, float]:
    """Term→IDF map, cached with a TTL. Empty dict on failure (caller then falls
    back to unweighted overlap — no crash)."""
    global _cache
    t = now if now is not None else time.monotonic()
    if _cache is not None and (t - _cache["built_at"]) < _TTL_SECONDS:
        return _cache["idf"]
    try:
        built = await _build()
        built["built_at"] = t
        _cache = built
        return built["idf"]
    except Exception as e:  # pragma: no cover - defensive
        log.bind(event="lexical_idf_error", error=str(e)).warning("idf build failed")
        return _cache["idf"] if _cache else {}
