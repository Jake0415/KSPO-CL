"""Tests for the known-facts layer (contact-fact class)."""
from __future__ import annotations

import json

import pytest

from kspo_ingest.qa import facts as facts_mod
from kspo_ingest.qa.facts import (
    detect_intents,
    fact_to_source,
    lookup_facts,
)


@pytest.fixture
def facts_file(tmp_path):
    data = {
        "entities": [
            {
                "entity": "국민체육진흥공단",
                "aliases": ["국민체육진흥공단", "공단", "kspo"],
                "fields": {
                    "address": {"value": "서울 송파구 올림픽로 424", "source": "https://www.kspo.or.kr/a"},
                    "phone": {"value": "02-410-1114", "source": "https://www.kspo.or.kr/b"},
                },
            },
            {
                "entity": "소마미술관",
                "aliases": ["소마미술관", "소마"],
                "fields": {
                    "address": {"value": "송파구 올림픽로 424", "source": "https://soma.kspo.or.kr/x"},
                },
            },
        ]
    }
    p = tmp_path / "known_facts.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    facts_mod._load.cache_clear()
    yield str(p)
    facts_mod._load.cache_clear()


def test_detect_intents():
    assert "address" in detect_intents("국민체육진흥공단의 위치는 어디인가요?")
    assert "phone" in detect_intents("공단 대표번호 알려줘")
    assert detect_intents("올림픽수영장 프로그램이 있나요?") == set()


def test_lookup_returns_address_with_source(facts_file):
    out = lookup_facts("국민체육진흥공단의 위치는 어디인가요?", path=facts_file)
    assert len(out) == 1
    assert out[0].field == "address"
    assert "올림픽로 424" in out[0].value
    assert out[0].source == "https://www.kspo.or.kr/a"


def test_intent_gate_no_contact_intent_returns_empty(facts_file):
    # entity present but no contact intent -> no fact injected (no regression)
    assert lookup_facts("국민체육진흥공단은 어떤 기관인가요?", path=facts_file) == []


def test_no_entity_returns_empty(facts_file):
    # contact intent but no known entity -> empty
    assert lookup_facts("올림픽수영장 위치는 어디인가요?", path=facts_file) == []


def test_only_asked_field_returned(facts_file):
    # asks address only -> phone must not leak
    out = lookup_facts("공단 주소가 어디인가요?", path=facts_file)
    assert {f.field for f in out} == {"address"}


def test_longest_alias_wins(facts_file):
    # "소마미술관 주소" should resolve 소마미술관, not 공단
    out = lookup_facts("소마미술관 주소 알려줘", path=facts_file)
    assert len(out) == 1 and out[0].entity == "소마미술관"


def test_english_alias_case_insensitive(facts_file):
    # lowercase JSON alias "kspo" must resolve regardless of query casing.
    for q in ["KSPO 주소", "Kspo 주소", "kspo 주소"]:
        out = lookup_facts(q, path=facts_file)
        assert len(out) == 1 and out[0].field == "address", q
        assert "올림픽로 424" in out[0].value


def test_fact_to_source_shape(facts_file):
    out = lookup_facts("공단 위치 어디?", path=facts_file)
    src = fact_to_source(out[0])
    assert src["score"] == 1.0
    assert src["source"] == "https://www.kspo.or.kr/a"
    assert "올림픽로 424" in src["page_content"]
    assert src["domain_host"] == "www.kspo.or.kr"


def test_real_config_loads_and_resolves_hq_address():
    # the shipped configs/known_facts.json must resolve the HQ address
    facts_mod._load.cache_clear()
    out = lookup_facts("국민체육진흥공단의 위치는 어디인가요?")
    facts_mod._load.cache_clear()
    assert any(f.field == "address" and "올림픽로 424" in f.value for f in out)


def test_fee_field_intent_and_lookup(tmp_path):
    data = {"entities": [{
        "entity": "국민체력100", "aliases": ["국민체력100", "체력측정"],
        "fields": {"fee": {"value": "무료", "source": "https://www.kspo.or.kr/x"}},
    }]}
    p = tmp_path / "kf.json"; p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    facts_mod._load.cache_clear()
    assert "fee" in detect_intents("체력측정 비용은 얼마인가요?")
    out = lookup_facts("체력측정 비용은?", path=str(p))
    facts_mod._load.cache_clear()
    assert len(out) == 1 and out[0].field == "fee" and out[0].value == "무료"


def test_real_config_national_fitness_is_free():
    facts_mod._load.cache_clear()
    out = lookup_facts("체력 측정 비용은?")
    facts_mod._load.cache_clear()
    assert any(f.field == "fee" and "무료" in f.value for f in out)


def test_reservation_field_and_facility_no_false_match(tmp_path):
    # 국민체력100 예약은 매칭, 올림픽수영장 예약은 미매칭(엔티티 다름) — 오주입 없음
    data = {"entities": [{
        "entity": "국민체력100", "aliases": ["국민체력100", "체력측정"],
        "fields": {"reservation": {"value": "매월 1일·16일 오후 1시 오픈", "source": "https://nfa.kspo.or.kr/beforeReserve.kspo"}},
    }]}
    p = tmp_path / "kf.json"; p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    facts_mod._load.cache_clear()
    out = lookup_facts("체력측정 예약은 어떻게 하나요?", path=str(p))
    assert len(out) == 1 and out[0].field == "reservation"
    assert lookup_facts("올림픽수영장 예약은 어떻게 하나요?", path=str(p)) == []
    facts_mod._load.cache_clear()
