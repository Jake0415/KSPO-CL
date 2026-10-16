from __future__ import annotations

import pytest

from kspo_ingest.crawl.youtube_caption import parse_timedtext_json


SAMPLE_TIMEDTEXT = {
    "events": [
        {"segs": [{"utf8": "안녕하세요"}], "tStartMs": 0, "dDurationMs": 2000},
        {"segs": [{"utf8": " 오늘은"}], "tStartMs": 2000, "dDurationMs": 1500},
        {"segs": [{"utf8": " 스트레칭을"}], "tStartMs": 3500, "dDurationMs": 1000},
        {"segs": [{"utf8": " 해볼게요"}], "tStartMs": 4500, "dDurationMs": 1500},
        {"segs": [{"utf8": "\n"}], "tStartMs": 6000, "dDurationMs": 500},
        {"segs": [{"utf8": "먼저 팔을 올려주세요"}], "tStartMs": 6500, "dDurationMs": 2000},
    ]
}


def test_parse_timedtext_json():
    text = parse_timedtext_json(SAMPLE_TIMEDTEXT)
    assert "안녕하세요" in text
    assert "스트레칭" in text
    assert "팔을 올려주세요" in text


def test_parse_timedtext_removes_extra_whitespace():
    text = parse_timedtext_json(SAMPLE_TIMEDTEXT)
    assert "  " not in text


def test_parse_empty_events():
    assert parse_timedtext_json({"events": []}) == ""


def test_parse_missing_segs():
    data = {"events": [{"tStartMs": 0, "dDurationMs": 1000}]}
    assert parse_timedtext_json(data) == ""


def test_parse_produces_nonempty_lines():
    text = parse_timedtext_json(SAMPLE_TIMEDTEXT)
    lines = [l for l in text.split("\n") if l.strip()]
    assert len(lines) >= 1
