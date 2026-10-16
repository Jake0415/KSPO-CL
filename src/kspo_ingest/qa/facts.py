"""Known-facts layer for canonical entity contact information.

Audit finding: contact facts (address, phone, email, hours) are stated in the
corpus in prose without trigger keywords ("…는 서울시 송파구 올림픽로 424에 있으며")
or on subsidiary domains, so pure dense retrieval under-ranks them and a naive
keyword hybrid regressed the majority of non-contact questions.

This layer resolves the *entire contact-fact class* deterministically: for a
query showing contact/location/hours intent AND naming a known entity, it returns
the curated, corpus-grounded fact plus its source URL for citation. It fires only
on that intersection, so non-contact queries are untouched (no regression).

Facts live in ``configs/known_facts.json`` — every value is backed by a crawled
source URL, so answers stay authoritative and explainable.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Intent → trigger tokens. A query must contain at least one to enable that field.
_INTENT_TRIGGERS: dict[str, tuple[str, ...]] = {
    "address": ("위치", "주소", "어디", "소재지", "오시는", "찾아오", "위치는"),
    "phone": ("전화", "연락처", "문의처", "대표번호", "전화번호", "연락"),
    "email": ("이메일", "메일", "전자우편"),
    "hours": ("운영시간", "이용시간", "영업시간", "개방시간", "관람시간", "몇시"),
    "fee": ("비용", "요금", "얼마", "무료", "유료", "이용료", "가격", "입장료", "관람료"),
    "reservation": ("예약", "신청", "예약방법", "예약일", "예약하려", "접수"),
}

_FIELD_LABEL = {
    "address": "주소",
    "phone": "전화번호",
    "email": "이메일",
    "hours": "운영시간",
    "fee": "이용요금",
    "reservation": "예약 안내",
}

# Order in which fields are emitted (also the field-iteration order in lookup).
_FIELDS = ("address", "phone", "email", "hours", "fee", "reservation")


@dataclass(frozen=True)
class Fact:
    entity: str
    field: str          # address | phone | email | hours
    label: str          # Korean label for the field
    value: str
    source: str


def _default_path() -> Path:
    # configs/known_facts.json at the repo root (…/kspo-ingest/configs/…)
    return Path(__file__).resolve().parents[3] / "configs" / "known_facts.json"


@lru_cache(maxsize=1)
def _load(path_str: str | None) -> list[dict]:
    path = Path(path_str) if path_str else _default_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data.get("entities", [])


def detect_intents(query: str) -> set[str]:
    """Which contact-fact fields the query is asking about (may be empty)."""
    q = query or ""
    return {
        field
        for field, triggers in _INTENT_TRIGGERS.items()
        if any(t in q for t in triggers)
    }


def _resolve_entity(query: str, entities: list[dict]) -> dict | None:
    """Longest alias contained in the query wins (avoids matching '공단' when a
    more specific '소마미술관' is present).

    Matching is case-insensitive so English aliases resolve regardless of the
    user's casing (e.g. ``KSPO``/``Kspo``/``kspo`` all match the ``kspo`` alias).
    """
    q = (query or "").lower()
    best: dict | None = None
    best_len = 0
    for ent in entities:
        for alias in ent.get("aliases", []):
            if alias and alias.lower() in q and len(alias) > best_len:
                best, best_len = ent, len(alias)
    return best


def lookup_facts(query: str, *, path: str | None = None) -> list[Fact]:
    """Return curated facts for the query, or [] if no contact intent / no entity.

    Only the intersection (asked-about field × available field on the resolved
    entity) is returned, so an address question never leaks an unrelated phone.
    """
    intents = detect_intents(query)
    if not intents:
        return []
    entities = _load(path)
    ent = _resolve_entity(query, entities)
    if ent is None:
        return []
    out: list[Fact] = []
    for field in _FIELDS:
        if field in intents and field in ent.get("fields", {}):
            f = ent["fields"][field]
            out.append(
                Fact(
                    entity=ent["entity"],
                    field=field,
                    label=_FIELD_LABEL[field],
                    value=f["value"],
                    source=f["source"],
                )
            )
    return out


def fact_to_source(fact: Fact) -> dict:
    """Adapt a Fact to the answerer's ``sources`` dict shape so it can be placed
    in the prompt context and resolved by positional citation."""
    host = ""
    m = re.search(r"https?://([^/]+)", fact.source)
    if m:
        host = m.group(1)
    content = (
        f"[제목] {fact.entity} {fact.label}\n"
        f"[본문] {fact.entity}의 {fact.label}: {fact.value}"
    )
    return {
        "source": fact.source,
        "title": f"{fact.entity} {fact.label}",
        "domain_host": host,
        "score": 1.0,  # curated canonical fact — highest authority
        "page_content": content,
    }
