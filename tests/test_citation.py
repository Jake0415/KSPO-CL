from __future__ import annotations

from kspo_ingest.qa.citation import parse_citations, Citation


def test_parse_single_citation():
    text = "올림픽공원은 송파구에 있습니다 [1]."
    sources = [{"source": "https://www.kspo.or.kr/park", "title": "올림픽공원", "domain_host": "www.kspo.or.kr"}]
    _, citations = parse_citations(text, sources)
    assert len(citations) == 1
    assert citations[0].index == 1
    assert citations[0].source_url == "https://www.kspo.or.kr/park"


def test_parse_multiple_citations():
    text = "경륜은 자전거 경주[1]이고 경정은 모터보트[2]입니다."
    sources = [
        {"source": "url1", "title": "경륜"},
        {"source": "url2", "title": "경정"},
    ]
    _, citations = parse_citations(text, sources)
    assert len(citations) == 2


def test_parse_duplicate_citations():
    text = "정보[1]를 참고하세요[1]."
    sources = [{"source": "url1"}]
    _, citations = parse_citations(text, sources)
    assert len(citations) == 1  # Deduplicated


def test_parse_out_of_range():
    text = "출처[5] 없음."
    sources = [{"source": "url1"}]
    _, citations = parse_citations(text, sources)
    assert len(citations) == 0


def test_parse_no_citations():
    text = "인용 없는 답변입니다."
    _, citations = parse_citations(text, [])
    assert len(citations) == 0
