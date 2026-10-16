"""SimHash near-duplicate detection tests."""
from __future__ import annotations

from kspo_ingest.quality.dedup import (
    compute_duplicate_score,
    hamming_distance,
    simhash,
)


class TestSimHash:
    def test_identical_texts_same_hash(self):
        a = simhash("국민체육진흥공단 공고 안내문입니다")
        b = simhash("국민체육진흥공단 공고 안내문입니다")
        assert a == b

    def test_different_texts_different_hash(self):
        a = simhash("국민체육진흥공단 공고 안내문입니다")
        b = simhash("올림픽공원 테니스장 예약 안내")
        assert a != b

    def test_similar_texts_close_distance(self):
        a = simhash("국민체육진흥공단 공고 안내문입니다 상세 내용")
        b = simhash("국민체육진흥공단 공고 안내문입니다 추가 내용")
        dist = hamming_distance(a, b)
        assert dist < 10  # similar texts should be close

    def test_empty_text_returns_zero(self):
        assert simhash("") == 0
        assert simhash("   ") == 0

    def test_returns_64bit_int(self):
        h = simhash("테스트 문서 본문입니다")
        assert isinstance(h, int)
        assert 0 <= h < (1 << 64)


class TestHammingDistance:
    def test_same_hash_zero_distance(self):
        assert hamming_distance(0b1010, 0b1010) == 0

    def test_one_bit_diff(self):
        assert hamming_distance(0b1010, 0b1011) == 1

    def test_all_bits_diff(self):
        assert hamming_distance(0, (1 << 64) - 1) == 64


class TestComputeDuplicateScore:
    def test_no_existing_hashes_returns_unique(self):
        assert compute_duplicate_score(123, []) == 1.0

    def test_exact_duplicate_returns_zero(self):
        h = simhash("국민체육진흥공단 공고 안내문입니다")
        assert compute_duplicate_score(h, [h]) == 0.0

    def test_different_doc_returns_unique(self):
        a = simhash("국민체육진흥공단 공고 안내문입니다")
        b = simhash("올림픽공원 테니스장 예약 안내입니다")
        assert compute_duplicate_score(a, [b]) == 1.0

    def test_threshold_boundary(self):
        h = 0b1111
        close = 0b1110  # distance 1
        assert compute_duplicate_score(h, [close], threshold=3) == 0.0

        far = h ^ 0b1111_0000  # distance 4
        assert compute_duplicate_score(h, [far], threshold=3) == 1.0
