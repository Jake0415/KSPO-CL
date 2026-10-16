"""Tests for domain-vocabulary query expansion (retrieval recall)."""
from __future__ import annotations

from kspo_ingest.qa.expansion import expand_query


def test_expands_representative_synonym():
    out = expand_query("체육진흥공단 대표자")
    assert "이사장" in out and out.startswith("체육진흥공단 대표자")


def test_expands_toto_to_official_term():
    out = expand_query("스포츠토토는 어떤 사업이야")
    assert "체육진흥투표권" in out


def test_no_trigger_returns_unchanged():
    q = "체육진흥공단 주소"
    assert expand_query(q) == q


def test_does_not_fire_on_daepyo_substring():
    # "대표전화"/"대표번호" contain "대표" but must NOT pull in "이사장" (would
    # pollute phone-contact retrieval).
    for q in ("체육진흥공단 대표전화", "공단 대표번호 알려줘"):
        assert "이사장" not in expand_query(q), q


def test_does_not_duplicate_present_canonical_term():
    # if the canonical term is already in the query, don't append it again
    out = expand_query("체육진흥공단 이사장 대표자")
    assert out.count("이사장") == 1


def test_empty_query_safe():
    assert expand_query("") == ""


def test_expands_department_to_org_vocab():
    out = expand_query("체육진흥공단 부서 안내")
    assert "조직도" in out and "직원안내" in out
