"""수동 크롤 입력에서 host 추출 헬퍼 단위 테스트."""
from __future__ import annotations

import pytest

from kspo_ingest.api.routers.jobs import _extract_host


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("www.kspo.or.kr", "www.kspo.or.kr"),
        ("https://www.kspo.or.kr/foo?bar=1", "www.kspo.or.kr"),
        ("http://nfa.kspo.or.kr/main.kspo", "nfa.kspo.or.kr"),
        ("WWW.KSPO.OR.KR", "www.kspo.or.kr"),
        ("  www.kspo.or.kr  ", "www.kspo.or.kr"),
        ("www.kspo.or.kr:8080/path", "www.kspo.or.kr"),
        ("//www.kspo.or.kr/x", "www.kspo.or.kr"),
    ],
)
def test_extract_host_valid(raw, expected):
    assert _extract_host(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "https://", "/", "http:///path"])
def test_extract_host_invalid(raw):
    with pytest.raises(ValueError):
        _extract_host(raw)
