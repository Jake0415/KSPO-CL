# tests/test_ingest_videos.py
from __future__ import annotations

import pytest

from kspo_ingest.tasks.pipeline.ingest_videos import build_video_chunk_text


def test_build_video_chunk_text():
    text = build_video_chunk_text(
        title="점핑점핑해요",
        target_age="유아기",
        fitness_item="심폐지구력",
        equipment="목봉/사다리",
        body_part="전신",
        caption_text="오늘은 점핑 운동을 해볼 거예요. 먼저 두 발을 모으고 뛰어봅시다.",
    )
    assert "[국민체력100 운동처방 | nfa.kspo.or.kr]" in text
    assert "점핑점핑해요" in text
    assert "유아기" in text
    assert "심폐지구력" in text
    assert "점핑 운동" in text


def test_build_video_chunk_text_no_caption():
    text = build_video_chunk_text(
        title="테스트 운동",
        target_age="성인",
        fitness_item="근력",
        equipment="맨몸",
        body_part="상체",
        caption_text="",
    )
    assert "테스트 운동" in text
    assert "성인" in text
