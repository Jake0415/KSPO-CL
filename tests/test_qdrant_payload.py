from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kspo_ingest.qdrant.payload import PayloadInput, build_payload
from kspo_ingest.settings import settings


def _full_input(**overrides) -> PayloadInput:
    base = {
        "chunk_id_sha1": "a" * 40,
        "text_with_header": "[제목] x\n[도메인] a.com\n\n— 본문 —\n본문",
        "source_url": "https://a.com/1",
        "domain_host": "a.com",
        "title": "공고",
        "summary": "요약",
        "keywords": ["KSPO", "공고"],
        "posted_at": datetime(2026, 4, 1, tzinfo=UTC),
        "is_attachment": False,
        "attachment_id": None,
        "attachment_name": None,
        "attachment_download_url": None,
        "parent_page_id": None,
        "parent_page_url": None,
        "embedding_version": 1,
    }
    base.update(overrides)
    return PayloadInput(**base)


def test_all_fields_populated_schema():
    p = build_payload(_full_input())
    assert p["page_content"].startswith("[제목] x")
    md = p["metadata"]
    assert set(md.keys()) >= {
        "id", "source", "namespace", "type", "domain_host",
        "title", "summary", "keywords", "posted_at", "last_indexed_at",
        "is_attachment", "attachment_id", "attachment_name",
        "attachment_download_url", "parent_page_id", "parent_page_url",
        "embedding_version", "tags",
    }


def test_namespace_is_settings_kb_namespace():
    p = build_payload(_full_input())
    assert p["metadata"]["namespace"] == settings.kb_namespace
    assert p["metadata"]["namespace"] == "kspo"


def test_posted_at_none_keeps_key_as_none():
    p = build_payload(_full_input(posted_at=None))
    assert "posted_at" in p["metadata"]
    assert p["metadata"]["posted_at"] is None


def test_posted_at_serialized_as_iso():
    dt = datetime(2026, 4, 1, 9, 30, tzinfo=UTC)
    p = build_payload(_full_input(posted_at=dt))
    assert p["metadata"]["posted_at"] == dt.isoformat()


def test_page_chunk_attachment_fields_all_none():
    p = build_payload(_full_input(is_attachment=False))
    md = p["metadata"]
    assert md["is_attachment"] is False
    assert md["attachment_id"] is None
    assert md["attachment_name"] is None
    assert md["attachment_download_url"] is None


def test_attachment_chunk_attachment_fields_populated():
    p = build_payload(_full_input(
        is_attachment=True,
        attachment_id=42,
        attachment_name="안내.pdf",
        attachment_download_url="https://a.com/files/42",
        parent_page_id=99,
        parent_page_url="https://a.com/posts/99",
    ))
    md = p["metadata"]
    assert md["is_attachment"] is True
    assert md["attachment_id"] == 42
    assert md["attachment_name"] == "안내.pdf"
    assert md["attachment_download_url"] == "https://a.com/files/42"
    assert md["parent_page_id"] == 99


def test_last_indexed_at_is_recent():
    before = datetime.now(UTC)
    p = build_payload(_full_input())
    after = datetime.now(UTC)
    parsed = datetime.fromisoformat(p["metadata"]["last_indexed_at"])
    assert before - timedelta(seconds=1) <= parsed <= after + timedelta(seconds=1)


def test_tags_embedded_in_metadata():
    p = build_payload(_full_input(embedding_version=2))
    tags = p["metadata"]["tags"]
    assert "d:a.com" in tags
    assert "is_att:0" in tags
    assert "v:2" in tags
    assert "p:2026" in tags
    assert "p:2026-04" in tags


def test_keywords_list_is_copied_not_shared():
    """payload가 입력 keywords list를 외부와 공유하지 않아야 — 후속 변형으로 인한 오염 방지."""
    src = ["a", "b"]
    p = build_payload(_full_input(keywords=src))
    src.append("c")
    assert p["metadata"]["keywords"] == ["a", "b"]


def test_chunk_id_in_metadata_id_field():
    p = build_payload(_full_input(chunk_id_sha1="b" * 40))
    assert p["metadata"]["id"] == "b" * 40
