"""Answer-side retrieval hardening.

The ingest index contained http/https + trailing-slash twins of the same page
(~half of the ``tilellm`` collection before remediation). Pure top-k dense
search therefore wasted slots on duplicates and, lacking any authority or
lexical signal, under-ranked canonical org pages and exact-term factual chunks.

This module post-processes the raw vector candidates (over-fetched) into a
clean, reranked top-k:

  1. dedup near-duplicate bodies within the same page (http/https twins were
     refined independently, so their bodies are similar, not identical) while
     preserving genuinely distinct chunks; plus exact-body dedup across URLs;
  2. rerank = dense_score + w_auth * authority + w_lex * lexical_overlap, with
     small weights so dense dominates and authority/lexical only break near-ties.

All functions are pure and deterministic for unit testing.
"""
from __future__ import annotations

import re

# Authority tiers (0..1). Deliberately a *tie-break* signal — see w_auth in qa.py.
# Rationale: the canonical public portal is the most authoritative source for
# organization-level facts; facility/service subsidiaries are authoritative for
# their own facilities, so the boost must stay small enough not to displace a
# clearly-more-relevant family-site answer.
_AUTHORITY: dict[str, float] = {
    "www.kspo.or.kr": 1.0,
    "kspo.or.kr": 1.0,
    "nfa.kspo.or.kr": 0.9,  # 국민체력100 공식
}
_KSPO_SUBDOMAIN_RE = re.compile(r"\.kspo\.or\.kr$")

_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")


def content_identity(source_url: str) -> str:
    """Scheme- and trailing-slash-insensitive identity for a page.

    ``http://h/p``, ``https://h/p`` and ``https://h/p/`` collapse to one id.
    Query string is preserved (distinguishes board posts by nttId etc.).
    """
    u = source_url or ""
    u = re.sub(r"^https?://", "", u)
    # split off query, strip trailing slash from the path portion only
    if "?" in u:
        path, q = u.split("?", 1)
        return path.rstrip("/").lower() + "?" + q
    return u.rstrip("/").lower()


def authority_weight(domain_host: str | None, source_url: str | None) -> float:
    """Return a 0..1 authority tier for the source host."""
    host = (domain_host or "").lower()
    if not host and source_url:
        host = content_identity(source_url).split("/", 1)[0].split("?", 1)[0]
    if host in _AUTHORITY:
        return _AUTHORITY[host]
    if _KSPO_SUBDOMAIN_RE.search(host):
        return 0.6  # kspo.or.kr service subdomain (spobiz, svoucher, soma, ...)
    if host.endswith("ksponco.or.kr"):
        return 0.5  # 한국체육산업개발 (시설 운영 자회사)
    return 0.4  # other family / external


def _tokens(text: str) -> set[str]:
    # drop 1-char tokens: too noisy for overlap in Korean/eng mixed text
    return {t for t in _TOKEN_RE.findall(text or "") if len(t) > 1}


def lexical_overlap(
    query: str, content: str, idf: dict[str, float] | None = None
) -> float:
    """Fraction of query terms present in the content (0..1). Cheap BM25-lite.

    When an ``idf`` map is supplied, terms are weighted by inverse document
    frequency: the score is the IDF mass of matched query terms over the total
    IDF mass of the query. This makes ubiquitous boilerplate terms (the org name,
    present in ~every chunk → IDF≈0) contribute almost nothing while rare,
    discriminative terms carry the signal — so an exact-term page is no longer
    diluted by the org name it shares with every generic chunk. Falls back to the
    unweighted fraction when no ``idf`` is given (or the query has no known terms).
    """
    q = _tokens(query)
    if not q:
        return 0.0
    c = _tokens(content)
    if idf:
        total = sum(idf.get(t, 0.0) for t in q)
        if total > 0:
            return sum(idf.get(t, 0.0) for t in (q & c)) / total
    return len(q & c) / len(q)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# Within one page, http/https twins were refined by the LLM independently, so
# their bodies are *similar but not identical* (median token-Jaccard ~0.61),
# while genuinely distinct chunks of a page sit lower (~0.35). Collapse above
# this threshold; bias toward preserving content.
_NEAR_DUP_JACCARD = 0.55

# Paginated list/menu pages (e.g. "공단 30년사(목록)", "고객의 소리") share an
# identical title and near-identical boilerplate body across ?pageIndex= URLs,
# so a single query pulls a dozen twins that flood top-k and crowd out diverse
# relevant chunks. These twins measure token-Jaccard 0.51–0.81, while genuinely
# distinct articles that merely share a section title (e.g. "보도자료(상세)")
# measure 0.10–0.13 — a wide, safe gap. Collapse same-title bodies above this
# cross-URL threshold; kept comfortably below distinct-article overlap.
_TITLE_NEAR_DUP_JACCARD = 0.5


def dedup_and_rerank(
    candidates: list[dict],
    query: str,
    top_k: int,
    *,
    w_auth: float = 0.02,
    w_lex: float = 0.03,
    idf: dict[str, float] | None = None,
) -> list[dict]:
    """Collapse duplicate pages, rerank, and return the top_k.

    ``candidates`` are dicts with keys: source, title, domain_host, score,
    page_content. Input order need not be sorted. Returns new dicts with an
    added ``rerank_score`` for explainability.

    ``idf`` (optional) enables IDF-weighted lexical scoring so a rare, exact query
    term (e.g. 인재상) outweighs the ubiquitous org name shared by every chunk.
    """
    # 1) dedup, keeping the highest dense score. Two mechanisms:
    #    (a) within the SAME page (normalized URL, scheme-insensitive): collapse
    #        near-duplicate bodies — the http/https twins whose summaries were
    #        refined separately — while preserving genuinely distinct chunks;
    #    (b) across DIFFERENT URLs: collapse byte-identical bodies (shared
    #        boilerplate stubs).
    ordered = sorted(candidates, key=lambda c: c.get("score", 0.0), reverse=True)
    kept: list[dict] = []
    kept_by_url: dict[str, list[set[str]]] = {}
    kept_by_title: dict[str, list[set[str]]] = {}
    seen_bodies: set[str] = set()
    for c in ordered:
        body = (c.get("page_content") or "").strip()
        if body and body in seen_bodies:  # (b) exact boilerplate across URLs
            continue
        cid = content_identity(c.get("source", ""))
        title = (c.get("title") or "").strip()
        tok = _tokens(body)
        # (a) twin / reflow of an already-kept chunk of the SAME page (scheme-
        #     insensitive URL); http/https summaries were refined separately.
        is_near_dup = any(
            _jaccard(tok, prev) >= _NEAR_DUP_JACCARD for prev in kept_by_url.get(cid, [])
        )
        # (c) paginated list/menu twin across DIFFERENT URLs but identical title
        #     and near-identical body — collapse to one representative.
        if not is_near_dup and title:
            is_near_dup = any(
                _jaccard(tok, prev) >= _TITLE_NEAR_DUP_JACCARD
                for prev in kept_by_title.get(title, [])
            )
        if is_near_dup:
            continue
        kept.append(c)
        kept_by_url.setdefault(cid, []).append(tok)
        if title:
            kept_by_title.setdefault(title, []).append(tok)
        if body:
            seen_bodies.add(body)

    # 2) rerank.
    ranked: list[dict] = []
    for c in kept:
        dense = float(c.get("score", 0.0))
        auth = authority_weight(c.get("domain_host"), c.get("source"))
        lex = lexical_overlap(query, c.get("page_content", ""), idf)
        out = dict(c)
        out["rerank_score"] = dense + w_auth * auth + w_lex * lex
        ranked.append(out)

    ranked.sort(key=lambda c: c["rerank_score"], reverse=True)
    return ranked[:top_k]
