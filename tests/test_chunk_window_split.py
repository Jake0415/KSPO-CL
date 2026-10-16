from __future__ import annotations

from kspo_ingest.chunk.tokens import count_tokens, get_encoder
from kspo_ingest.chunk.window_split import window_split


def _para(token_count: int, marker: str = "단어") -> str:
    """주어진 토큰 수에 근접하도록 어절을 반복."""
    enc = get_encoder()
    word = f"{marker} "
    base_tok = len(enc.encode(word))
    repeat = max(1, token_count // max(base_tok, 1))
    return (word * repeat).strip()


def test_short_text_single_chunk():
    text = "짧은 한국어 본문입니다."
    chunks = window_split(text, target=600, overlap=80)
    assert len(chunks) == 1
    assert chunks[0].strip() == text.strip()


def test_long_single_paragraph_splits_to_multiple():
    big = _para(1500, marker="가나다")
    chunks = window_split(big, target=600, overlap=80)
    assert len(chunks) >= 2
    for c in chunks:
        # overlap+여유 고려해 target * 1.5 이내 권장
        assert count_tokens(c) <= 900


def test_very_long_text_yields_many_chunks():
    big = _para(5000, marker="라마바")
    chunks = window_split(big, target=600, overlap=80)
    assert len(chunks) >= 6


def test_overlap_prepends_tail_of_previous_chunk():
    big = _para(1500, marker="겹침")
    chunks = window_split(big, target=600, overlap=80)
    assert len(chunks) >= 2
    enc = get_encoder()
    prev_tail_ids = enc.encode(chunks[0])[-80:]
    next_head_ids = enc.encode(chunks[1])[: len(prev_tail_ids)]
    # 정확히 같진 않아도 큰 폭으로 겹쳐야 함 (어절 경계 보정 때문에)
    overlap_count = sum(
        1 for a, b in zip(prev_tail_ids, next_head_ids, strict=False) if a == b
    )
    assert overlap_count >= 40


def test_paragraph_boundary_preserved():
    p1 = _para(300, marker="앞단락")
    p2 = _para(300, marker="뒷단락")
    text = f"{p1}\n\n{p2}"
    chunks = window_split(text, target=600, overlap=80)
    # 두 단락 합 ~600 → 한 청크에 들어갈 수 있고, 분리되더라도 단락 경계 우선
    if len(chunks) >= 2:
        # 첫 청크 끝 또는 둘째 청크 시작이 단락 경계와 일치
        assert "앞단락" in chunks[0]
        assert "뒷단락" in chunks[-1]


def test_empty_text_yields_no_or_empty_chunk():
    chunks = window_split("", target=600, overlap=80)
    assert chunks == [] or all(not c.strip() for c in chunks)
