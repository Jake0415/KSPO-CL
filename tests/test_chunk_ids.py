from __future__ import annotations

import uuid

from kspo_ingest.chunk.ids import NAMESPACE_KSPO, chunk_id_sha1, to_qdrant_point_id


def test_same_input_same_sha1_and_uuid():
    s1 = chunk_id_sha1(123, 1, 0, False, None)
    s2 = chunk_id_sha1(123, 1, 0, False, None)
    assert s1 == s2
    assert to_qdrant_point_id(s1) == to_qdrant_point_id(s2)


def test_different_chunk_index_different_sha1():
    s0 = chunk_id_sha1(123, 1, 0, False, None)
    s1 = chunk_id_sha1(123, 1, 1, False, None)
    assert s0 != s1


def test_attachment_id_none_equals_zero():
    """`attachment_id or 0`이 None과 0을 동일 처리하는지 검증."""
    s_none = chunk_id_sha1(10, 1, 0, False, None)
    s_zero = chunk_id_sha1(10, 1, 0, False, 0)
    assert s_none == s_zero


def test_uuid5_uses_kspo_namespace():
    sha1 = chunk_id_sha1(7, 1, 0, True, 42)
    expected = uuid.uuid5(NAMESPACE_KSPO, sha1)
    assert to_qdrant_point_id(sha1) == expected


def test_is_attachment_flag_changes_sha1():
    s_page = chunk_id_sha1(5, 1, 0, False, None)
    s_att = chunk_id_sha1(5, 1, 0, True, 1)
    assert s_page != s_att


def test_sha1_is_40_hex():
    s = chunk_id_sha1(1, 1, 0, False, None)
    assert len(s) == 40
    int(s, 16)  # hex 검증
