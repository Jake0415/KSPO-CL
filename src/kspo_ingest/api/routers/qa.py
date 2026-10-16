"""POST /api/qa — 질의응답 프록시.

Qdrant 벡터 검색 → LLM 답변 생성 → 인용 파싱 → QaLog 기록.
"""
from __future__ import annotations

import time
from collections import OrderedDict

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from qdrant_client import models

from kspo_ingest.api.deps import SessionDep
from kspo_ingest.db.models import QaLog
from kspo_ingest.embed.openai_embed import embed_batch, get_embed_client
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.qa.citation import parse_citations
from kspo_ingest.qa.expansion import expand_query
from kspo_ingest.qa.facts import fact_to_source, lookup_facts
from kspo_ingest.qa.lexical_stats import get_idf
from kspo_ingest.qa.retrieval import dedup_and_rerank
from kspo_ingest.qdrant.client import get_client as get_qdrant
from kspo_ingest.refine.provider import get_provider
from kspo_ingest.settings import settings

router = APIRouter(prefix="/api/qa", tags=["qa"])
log = get_logger("api", "qa")

# OpenAI embeddings are NOT deterministic — re-embedding identical text returns
# vectors that differ by up to ~1e-2 (cosine as low as 0.992), which flips
# borderline chunks in/out of top-k and makes the same question return different
# answers run-to-run. Cache the query vector by (model, text) so a repeated query
# is byte-for-byte reproducible (also saves an embedding call). Bounded FIFO.
_QVEC_CACHE: "OrderedDict[tuple[str, str], list[float]]" = OrderedDict()
_QVEC_CACHE_MAX = 2048


async def _embed_query(client, model: str, text: str) -> list[float]:
    key = (model, text)
    cached = _QVEC_CACHE.get(key)
    if cached is not None:
        _QVEC_CACHE.move_to_end(key)
        return cached
    result = await embed_batch(client, model, [text])
    vec = result.vectors[0]
    _QVEC_CACHE[key] = vec
    if len(_QVEC_CACHE) > _QVEC_CACHE_MAX:
        _QVEC_CACHE.popitem(last=False)
    return vec


# When dense retrieval is LOW-confidence (its top score is weak, i.e. no chunk is a
# good semantic match), the answer page is usually buried past the candidate pool
# because the short query's org name is non-discriminative (e.g. 민원, 기관 소개).
# Rewriting the query into retrieval keywords via the LLM then finds it at rank 1.
# Gated on confidence so well-matched queries are untouched (no extra call, no
# regression). Cached per question for reproducibility + cost.
_REWRITE_GATE = 0.45
_REWRITE_PROMPT = (
    "다음 질문을 한국 공공기관(KSPO) 웹사이트 검색에 적합한 핵심 키워드 6~12개로만 "
    "확장하세요. 동의어와 상위/관련 개념을 포함하되, 설명 없이 공백으로 구분한 키워드만 "
    "출력하세요.\n질문: "
)
_REWRITE_CACHE: "OrderedDict[str, str]" = OrderedDict()


async def _rewrite_query(provider, question: str) -> str:
    if question in _REWRITE_CACHE:
        _REWRITE_CACHE.move_to_end(question)
        return _REWRITE_CACHE[question]
    try:
        r = await provider.chat_completion(
            messages=[{"role": "user", "content": _REWRITE_PROMPT + question}],
            temperature=0.0,
            seed=1,
        )
        rewritten = (r.choices[0].message.content or "").strip()
    except Exception:
        rewritten = ""
    _REWRITE_CACHE[question] = rewritten
    if len(_REWRITE_CACHE) > _QVEC_CACHE_MAX:
        _REWRITE_CACHE.popitem(last=False)
    return rewritten

QA_SYSTEM_PROMPT = (
    "당신은 KSPO(국민체육진흥공단) 웹사이트 정보를 바탕으로 질문에 답변하는 AI 어시스턴트입니다.\n"
    "다음 규칙을 지키세요.\n"
    "1. 답변은 반드시 제공된 컨텍스트에 근거해야 합니다. 컨텍스트에 없는 내용을 지어내지 마세요.\n"
    "2. 질문에 대한 정보가 컨텍스트 안에 있으면, 그 정보가 해당 문서의 주된 주제가 아니라 "
    "부수적으로 언급되었더라도 반드시 찾아내어 답변하세요. "
    "(예: 보도자료 본문에 등장하는 이사장 이름, 연혁 설명에 언급된 설립 연도, "
    "안내문 목록에 포함된 전화번호·주소 등)\n"
    "3. 관련 정보가 여러 컨텍스트에 흩어져 있으면 종합하여 답변하세요.\n"
    "4. 답변에 사용한 출처를 [1], [2] 형식으로 표기하세요.\n"
    "5. 컨텍스트 어디에서도 질문과 관련된 정보를 전혀 찾을 수 없을 때에만 "
    "\"해당 정보를 찾을 수 없습니다.\"라고 답하세요."
)


class QaRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    namespace: str = "kspo"
    debug: bool = False  # True → 검색 청크 본문 + 최종 프롬프트 반환 (Explain/Playground)


class QaSourceOut(BaseModel):
    source: str
    title: str | None = None
    domain_host: str | None = None
    score: float
    page_content: str | None = None  # debug 시 검색된 청크 본문


class QaResponse(BaseModel):
    answer: str
    sources: list[QaSourceOut]
    citations: list[dict]
    log_id: int
    latency_ms: int
    prompt: str | None = None  # debug: LLM에 전달된 컨텍스트
    system_prompt: str | None = None
    model: str | None = None


@router.post("", response_model=QaResponse)
async def ask(
    body: QaRequest,
    s: AsyncSession = SessionDep,
) -> dict:
    """질의응답 — Qdrant 검색 → LLM 답변 → 인용 → 로그."""
    t0 = time.monotonic()

    # 1. Embed question. Expand domain synonyms for the EMBEDDING query only so
    #    colloquial terms (대표자/스포츠토토) retrieve the corpus's canonical
    #    vocabulary (이사장/체육진흥투표권); the LLM still sees the original text.
    embed_client = get_embed_client()
    expanded_q = expand_query(body.question)
    q_vector = await _embed_query(embed_client, settings.openai_embed_model, expanded_q)

    # 2. Search Qdrant — over-fetch so dedup/rerank has candidates to work with.
    #    The index contains http/https + boilerplate twins (~54% of points); a
    #    bare top_k would waste slots on duplicates and expose no authority/lexical
    #    signal. We fetch a wider candidate pool, then collapse + rerank to top_k.
    #    fetch_k is over-fetched wider than a bare top_k so exact-term factual
    #    pages that dense under-ranks (the org name in the query is
    #    non-discriminative → they sit ~rank 20) still enter the candidate pool,
    #    where IDF-weighted lexical rerank can surface them.
    qdrant = get_qdrant()
    fetch_k = max(body.top_k * 8, 40)
    # Exact (brute-force) KNN so the candidate pool is byte-for-byte reproducible
    # run-to-run (HNSW is approximate; its deeper ranks shift between identical
    # queries and the IDF rerank amplifies that into different top-k). ~5k pts →
    # low-ms.
    exact = models.SearchParams(exact=True)
    # 컬렉션이 named vector로 구성된 경우(Tiledesk 외부 인스턴스: "text-dense")
    # 반드시 벡터 이름을 지정해야 한다. 빈값이면 None → unnamed(default) 벡터 조회.
    using = settings.qdrant_vector_name or None
    search_results = await qdrant.query_points(
        collection_name=settings.qdrant_index_name,
        query=q_vector, using=using, limit=fetch_k, with_payload=True, search_params=exact,
    )

    # Query Rewrite (gated): if dense found no strong match, the answer page is
    # likely buried past the pool — rewrite the question into retrieval keywords
    # and re-search. Fires only on low-confidence queries, so well-matched ones
    # are untouched (no regression, no extra LLM call).
    top_score = search_results.points[0].score if search_results.points else 0.0
    if top_score < _REWRITE_GATE:
        rewritten = await _rewrite_query(get_provider(), body.question)
        if rewritten:
            rq_vector = await _embed_query(
                embed_client, settings.openai_embed_model, f"{expanded_q} {rewritten}"
            )
            search_results = await qdrant.query_points(
                collection_name=settings.qdrant_index_name,
                query=rq_vector, using=using, limit=fetch_k, with_payload=True, search_params=exact,
            )

    candidates = []
    for point in search_results.points:
        payload = point.payload or {}
        metadata = payload.get("metadata", {})
        candidates.append(
            {
                "source": metadata.get("source", ""),
                "title": metadata.get("title"),
                "domain_host": metadata.get("domain_host"),
                "score": point.score,
                "page_content": payload.get("page_content", ""),
            }
        )

    # 3. Dedup duplicate pages + IDF-weighted lexical rerank of the dense pool.
    #    (The upstream root cause of undifferentiated dense scores — the org-name
    #    boilerplate header being embedded — is fixed at ingest: chunks are embedded
    #    on summary+body, not the full header. IDF reranking then only needs to
    #    break near-ties on rare exact terms.) Rerank on the EXPANDED query so a
    #    synonym-answer (대표자→이사장) matches the lexical signal too.
    idf = await get_idf()
    sources = dedup_and_rerank(
        candidates, query=expanded_q, top_k=body.top_k, w_lex=0.08, idf=idf
    )

    # 3b. Known-facts layer — for contact/location/hours questions about a known
    #     entity, prepend the curated, corpus-grounded fact (with its source) as
    #     the most authoritative context item. Fires only on contact-intent +
    #     entity match, so other questions are unaffected.
    fact_sources = [fact_to_source(f) for f in lookup_facts(body.question)]
    if fact_sources:
        sources = fact_sources + sources

    context_parts = [
        f"[{i + 1}] {s['page_content']}" for i, s in enumerate(sources)
    ]

    context = "\n\n".join(context_parts)

    # 4. Generate answer via LLM
    provider = get_provider()
    is_answered = True
    error_msg = None
    answer_text = ""

    try:
        if not sources:
            answer_text = "해당 정보를 찾을 수 없습니다."
            is_answered = False
        else:
            response = await provider.chat_completion(
                messages=[
                    {"role": "system", "content": QA_SYSTEM_PROMPT},
                    {"role": "user", "content": f"컨텍스트:\n{context}\n\n질문: {body.question}"},
                ],
                # Greedy decoding + fixed seed: retrieval is deterministic, so
                # temperature=0 with a fixed seed makes the answer reproducible
                # run-to-run (factual QA wants the single most-likely grounded
                # answer). LLM inference is otherwise non-deterministic even at
                # temperature 0; the seed requests best-effort reproducibility.
                temperature=0.0,
                seed=1,
            )
            answer_text = response.choices[0].message.content or ""
    except Exception as e:
        answer_text = "답변 생성 중 오류가 발생했습니다."
        is_answered = False
        error_msg = str(e)
        log.bind(event="qa_error", error=str(e)).warning("LLM answer generation failed")

    # 5. Parse citations
    _, citations = parse_citations(answer_text, sources)

    latency_ms = int((time.monotonic() - t0) * 1000)

    # 6. Log to QaLog
    qa_log = QaLog(
        question=body.question,
        answer=answer_text,
        sources={
            "results": [
                {"source": s["source"], "title": s.get("title"), "score": s["score"]}
                for s in sources
            ]
        },
        is_answered=is_answered,
        error_message=error_msg,
        latency_ms=latency_ms,
        provider=provider.name,
        model=provider.model,
    )
    s.add(qa_log)
    await s.commit()
    await s.refresh(qa_log)

    return {
        "answer": answer_text,
        "sources": [
            {
                "source": s["source"],
                "title": s.get("title"),
                "domain_host": s.get("domain_host"),
                "score": s["score"],
                "page_content": s.get("page_content") if body.debug else None,
            }
            for s in sources
        ],
        "prompt": (f"컨텍스트:\n{context}\n\n질문: {body.question}") if body.debug else None,
        "system_prompt": QA_SYSTEM_PROMPT if body.debug else None,
        "model": provider.model,
        "citations": [
            {"index": c.index, "source_url": c.source_url, "title": c.title}
            for c in citations
        ],
        "log_id": qa_log.id,
        "latency_ms": latency_ms,
    }
