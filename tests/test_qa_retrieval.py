"""Tests for answer-side retrieval hardening: dedup + authority/lexical rerank.

Defect classes covered:
  - Duplicate content (http/https + trailing-slash twins polluting top-k)
  - Authority/domain ranking (canonical HQ tie-break over family/service sites)
  - Hybrid/lexical signal (exact-term factual lookups under pure dense)
"""
from __future__ import annotations

from kspo_ingest.qa.retrieval import (
    authority_weight,
    content_identity,
    dedup_and_rerank,
    lexical_overlap,
)


def _cand(source, score, content="", title=None, host=None):
    return {
        "source": source,
        "title": title,
        "domain_host": host,
        "score": score,
        "page_content": content,
    }


# ---- content_identity: scheme + trailing-slash insensitive -------------------

def test_content_identity_collapses_scheme():
    a = content_identity("http://www.kspo.or.kr/a/b")
    b = content_identity("https://www.kspo.or.kr/a/b")
    assert a == b


def test_content_identity_collapses_trailing_slash():
    a = content_identity("https://x.kr/p")
    b = content_identity("https://x.kr/p/")
    assert a == b


def test_content_identity_keeps_query_distinct():
    a = content_identity("https://x.kr/v.do?nttId=1")
    b = content_identity("https://x.kr/v.do?nttId=2")
    assert a != b


# ---- dedup: http/https twins collapse, best score kept -----------------------

def test_dedup_collapses_http_https_twins():
    cands = [
        _cand("http://www.kspo.or.kr/p", 0.55, "x", host="www.kspo.or.kr"),
        _cand("https://www.kspo.or.kr/p", 0.54, "x", host="www.kspo.or.kr"),
        _cand("https://www.kspo.or.kr/q", 0.53, "y", host="www.kspo.or.kr"),
    ]
    out = dedup_and_rerank(cands, query="무엇", top_k=5, w_auth=0.0, w_lex=0.0)
    ids = {content_identity(c["source"]) for c in out}
    assert len(ids) == 2  # twins collapsed
    # the surviving twin keeps the higher dense score
    kept = next(c for c in out if content_identity(c["source"]).endswith("/p"))
    assert kept["score"] == 0.55


def test_dedup_preserves_distinct_chunks_of_same_page():
    # multiple chunks of ONE page share the source URL but differ in body —
    # they must NOT be collapsed (that would drop page content).
    cands = [
        _cand("https://a.kr/p", 0.60, "첫 번째 청크 본문 회원권 안내", host="a.kr"),
        _cand("https://a.kr/p", 0.50, "두 번째 청크 본문 이용 시간", host="a.kr"),
    ]
    out = dedup_and_rerank(cands, query="회원권", top_k=5, w_auth=0.0, w_lex=0.0)
    assert len(out) == 2


def test_dedup_collapses_near_duplicate_twins_same_page():
    # http/https twins: same page, independently refined -> similar (not identical)
    # bodies with high token overlap -> collapse to one.
    cands = [
        _cand("http://a.kr/p", 0.55, "국민체육진흥공단 조각공원 안내 야외 조각 산책로 광장 에서 감상", host="a.kr"),
        _cand("https://a.kr/p", 0.54, "국민체육진흥공단 조각공원 안내 야외 조각 산책로 에서 감상 광장", host="a.kr"),
    ]
    out = dedup_and_rerank(cands, query="조각공원", top_k=5, w_auth=0.0, w_lex=0.0)
    assert len(out) == 1
    assert out[0]["score"] == 0.55  # keeps the higher-scored twin


def test_dedup_collapses_identical_content_across_urls():
    cands = [
        _cand("https://a.kr/1", 0.5, "SAME BODY", host="a.kr"),
        _cand("https://a.kr/2", 0.49, "SAME BODY", host="a.kr"),
    ]
    out = dedup_and_rerank(cands, query="q", top_k=5, w_auth=0.0, w_lex=0.0)
    assert len(out) == 1


def test_dedup_collapses_paginated_list_twins_same_title():
    # Paginated list pages: identical title, different ?pageIndex= URL, and
    # near-identical boilerplate body (token-Jaccard ~0.6) -> collapse to one,
    # freeing top-k slots for diverse content.
    body_a = "고객의 소리 목록 안내 문의 전화 고객센터 1544 커뮤니티 스포츠강좌이용권 접수 처리"
    body_b = "고객의 소리 목록 안내 문의 전화 고객센터 1544 커뮤니티 스포츠강좌이용권 접수 확인"
    cands = [
        _cand("https://a.kr/list.do?pageIndex=1", 0.58, body_a, title="고객의 소리", host="a.kr"),
        _cand("https://a.kr/list.do?pageIndex=2", 0.57, body_b, title="고객의 소리", host="a.kr"),
        _cand("https://a.kr/list.do?pageIndex=3", 0.56, body_a, title="고객의 소리", host="a.kr"),
        _cand("https://a.kr/other", 0.50, "완전히 다른 주제의 페이지 본문 내용", title="다른 페이지", host="a.kr"),
    ]
    out = dedup_and_rerank(cands, query="고객센터", top_k=5, w_auth=0.0, w_lex=0.0)
    titles = [c["title"] for c in out]
    assert titles.count("고객의 소리") == 1  # twins collapsed to one
    assert "다른 페이지" in titles          # distinct page preserved


def test_dedup_keeps_distinct_articles_sharing_a_section_title():
    # Different articles under the same section title (e.g. "보도자료(상세)") have
    # low body overlap (~0.13) and must NOT be collapsed.
    cands = [
        _cand("https://a.kr/1", 0.55, "연탄 나눔 봉사활동 강남구 개포동 구룡마을 성금 기부 임직원", title="보도자료(상세)", host="a.kr"),
        _cand("https://a.kr/2", 0.54, "보조금24 서비스 행정안전부 유공표창 수상 스포츠산업 융자", title="보도자료(상세)", host="a.kr"),
    ]
    out = dedup_and_rerank(cands, query="보도자료", top_k=5, w_auth=0.0, w_lex=0.0)
    assert len(out) == 2  # distinct articles preserved despite shared title


def test_dedup_backfills_to_top_k():
    # 6 raw with 1 twin pair -> 5 unique; top_k=5 should return 5, not 4
    cands = [
        _cand("http://a.kr/p", 0.60, "a", host="a.kr"),
        _cand("https://a.kr/p", 0.59, "a", host="a.kr"),
        _cand("https://a.kr/2", 0.58, "b", host="a.kr"),
        _cand("https://a.kr/3", 0.57, "c", host="a.kr"),
        _cand("https://a.kr/4", 0.56, "d", host="a.kr"),
        _cand("https://a.kr/5", 0.55, "e", host="a.kr"),
    ]
    out = dedup_and_rerank(cands, query="q", top_k=5, w_auth=0.0, w_lex=0.0)
    assert len(out) == 5


# ---- authority: canonical HQ tie-break ---------------------------------------

def test_authority_hq_above_family():
    assert authority_weight("www.kspo.or.kr", "https://www.kspo.or.kr/x") > authority_weight(
        "www.ksponco.or.kr", "https://www.ksponco.or.kr/x"
    )


def test_authority_breaks_near_tie_only():
    # near-tie: HQ should win; large dense gap: family still wins
    near = [
        _cand("https://www.ksponco.or.kr/x", 0.550, "체육산업개발 시설 운영 소개", host="www.ksponco.or.kr"),
        _cand("https://www.kspo.or.kr/about", 0.548, "국민체육진흥공단 기관 소개", host="www.kspo.or.kr"),
    ]
    out = dedup_and_rerank(near, query="기관 소개", top_k=1, w_auth=0.03, w_lex=0.0)
    assert out[0]["domain_host"] == "www.kspo.or.kr"

    wide = [
        _cand("https://www.ksponco.or.kr/x", 0.70, "체육산업개발 시설 운영 소개", host="www.ksponco.or.kr"),
        _cand("https://www.kspo.or.kr/about", 0.50, "국민체육진흥공단 기관 소개", host="www.kspo.or.kr"),
    ]
    out2 = dedup_and_rerank(wide, query="국민체육진흥공단 소개", top_k=1, w_auth=0.03, w_lex=0.0)
    assert out2[0]["domain_host"] == "www.ksponco.or.kr"  # dense dominates big gaps


# ---- lexical: exact-term factual boost ---------------------------------------

def test_lexical_overlap_rewards_matching_terms():
    hi = lexical_overlap("이용료 요금 얼마", "성인 이용료 요금은 5000원")
    lo = lexical_overlap("이용료 요금 얼마", "올림픽공원 산책로 안내")
    assert hi > lo


def test_lexical_boost_surfaces_factual_chunk():
    cands = [
        _cand("https://a.kr/1", 0.52, "올림픽공원 일반 안내 페이지", host="a.kr"),
        _cand("https://a.kr/2", 0.50, "체육시설 이용료 요금표: 성인 5000원 청소년 3000원", host="a.kr"),
    ]
    out = dedup_and_rerank(cands, query="체육시설 이용료 요금", top_k=1, w_auth=0.0, w_lex=0.08)
    assert out[0]["source"] == "https://a.kr/2"


# ---- IDF-weighted lexical: rare exact term beats the ubiquitous org name ------

def test_idf_weight_downweights_ubiquitous_term():
    # 체육진흥공단 is in ~every doc (idf≈0); 인재상 is rare (idf high). A chunk
    # matching only the org name scores ~0; one matching the rare term scores ~1.
    idf = {"체육진흥공단": 0.01, "인재상": 5.0}
    hi = lexical_overlap("체육진흥공단 인재상", "국민체육진흥공단 인재상 비전 소개", idf)
    lo = lexical_overlap("체육진흥공단 인재상", "국민체육진흥공단 보도자료 연탄나눔", idf)
    assert hi > 0.9 and lo < 0.1


def test_idf_rerank_surfaces_exact_term_page_over_higher_dense_generic():
    # Generic chunk has higher dense score but only shares the org name; the
    # exact-term page has slightly lower dense but matches the rare term. With IDF
    # weighting + w_lex, the exact-term page must win (the 인재상 failure class).
    idf = {"체육진흥공단": 0.01, "인재상": 5.0, "비전": 4.0, "소개": 2.0}
    cands = [
        _cand("https://a.kr/generic", 0.523, "국민체육진흥공단 게시판 공지사항 상세", host="a.kr"),
        _cand("https://a.kr/talent", 0.471, "국민체육진흥공단 인재상 비전 소개 인사제도", host="a.kr"),
    ]
    out = dedup_and_rerank(
        cands, query="체육진흥공단 인재상", top_k=1, w_auth=0.0, w_lex=0.08, idf=idf
    )
    assert out[0]["source"] == "https://a.kr/talent"

    # without idf (unweighted) the tiny lexical edge cannot overcome the dense gap
    out_noidf = dedup_and_rerank(
        cands, query="체육진흥공단 인재상", top_k=1, w_auth=0.0, w_lex=0.03
    )
    assert out_noidf[0]["source"] == "https://a.kr/generic"
