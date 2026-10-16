from __future__ import annotations

import json
from datetime import UTC, datetime

from kspo_ingest.chunk.chunker import (
    AttachmentChunkInput,
    ChunkInput,
    chunk_attachment,
    chunk_page,
    write_chunks_jsonl,
)
from kspo_ingest.chunk.tokens import count_tokens, get_encoder

SAMPLE_DATE = datetime(2025, 4, 1, 9, 0, tzinfo=UTC)


def _para(token_count: int, marker: str) -> str:
    enc = get_encoder()
    word = f"{marker} "
    base = max(len(enc.encode(word)), 1)
    return (word * (token_count // base)).strip()


def _short_input(body: str = "짧은 본문입니다.") -> ChunkInput:
    return ChunkInput(
        page_id=42,
        embedding_version=1,
        domain_host="www.kspo.or.kr",
        title="공고",
        posted_at=SAMPLE_DATE,
        summary="요약",
        body_text=body,
    )


def test_short_page_yields_single_chunk_with_header():
    chunks = chunk_page(_short_input())
    assert len(chunks) == 1
    c = chunks[0]
    assert c.chunk_index == 0
    assert "[제목] 공고" in c.text
    assert "[도메인] www.kspo.or.kr" in c.text
    assert c.is_attachment is False
    assert c.attachment_id is None
    assert c.token_len == count_tokens(c.text)


def test_long_page_yields_multiple_chunks_each_with_header():
    body = _para(1500, marker="가나다")
    inp = _short_input(body)
    chunks = chunk_page(inp)
    assert len(chunks) >= 2
    for c in chunks:
        assert "[제목] 공고" in c.text
        assert c.is_attachment is False


def test_attachment_chunk_sets_attachment_fields():
    inp = AttachmentChunkInput(
        page_id=10,
        attachment_id=99,
        embedding_version=1,
        file_name="안내.pdf",
        parent_title="공고",
        parent_posted_at=SAMPLE_DATE,
        body_text="첨부 본문 텍스트입니다.",
    )
    chunks = chunk_attachment(inp)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.is_attachment is True
    assert c.attachment_id == 99
    assert "[첨부파일] 안내.pdf" in c.text
    assert "[부모 게시글] 공고" in c.text


def test_token_len_includes_header():
    inp = _short_input("아주 짧은 본문")
    chunks = chunk_page(inp)
    c = chunks[0]
    body_only = count_tokens("아주 짧은 본문")
    # header 포함이므로 본문 토큰 수보다 커야 함
    assert c.token_len > body_only


def test_write_chunks_jsonl(tmp_path):
    inp = _short_input()
    chunks = chunk_page(inp)
    path = write_chunks_jsonl(tmp_path, page_id=inp.page_id, chunks=chunks)
    assert path.exists()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(chunks)
    rec = json.loads(lines[0])
    assert rec["chunk_index"] == 0
    assert rec["chunk_id_sha1"] == chunks[0].chunk_id_sha1
    assert rec["qdrant_point_id"] == str(chunks[0].qdrant_point_id)
    assert "text" in rec


def test_idempotent_chunk_ids():
    inp = _short_input(_para(1500, marker="라마바"))
    a = chunk_page(inp)
    b = chunk_page(inp)
    assert len(a) == len(b)
    for ca, cb in zip(a, b, strict=True):
        assert ca.chunk_id_sha1 == cb.chunk_id_sha1
        assert ca.qdrant_point_id == cb.qdrant_point_id
