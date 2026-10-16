from __future__ import annotations

import pytest

from kspo_ingest.crawl.nfa_video import VideoMeta, parse_video_list_html, parse_youtube_id_from_viewer


SAMPLE_LIST_HTML = """
<div class="movieArea">
  <ul class="movieList">
    <li>
      <button onclick='fnMovieViewerOpen("2279",this)'>
        <span class="tit">점핑점핑해요</span>
      </button>
      <dl class="infoArea">
        <dd>심폐지구력</dd>
        <dd>목봉/사다리</dd>
        <dd>전신</dd>
        <dd>유아기</dd>
      </dl>
    </li>
    <li>
      <button onclick='fnMovieViewerOpen("2287",this)'>
        <span class="tit">흔들어 체조</span>
      </button>
      <dl class="infoArea">
        <dd>유연성</dd>
        <dd>맨몸</dd>
        <dd>전신</dd>
        <dd>유아기</dd>
      </dl>
    </li>
  </ul>
</div>
"""

SAMPLE_VIEWER_HTML = """
<div class="movieViewer">
  <iframe src="https://www.youtube.com/embed/KlDL8qiVZuA?cc_lang_pref=ko&cc_load_policy=1&autoplay=1"></iframe>
</div>
"""


def test_parse_video_list():
    videos = parse_video_list_html(SAMPLE_LIST_HTML)
    assert len(videos) == 2
    assert videos[0].movie_sn == "2279"
    assert videos[0].title == "점핑점핑해요"


def test_parse_video_metadata():
    videos = parse_video_list_html(SAMPLE_LIST_HTML)
    v = videos[0]
    assert v.fitness_item == "심폐지구력"
    assert v.equipment == "목봉/사다리"
    assert v.target_age == "유아기"


def test_parse_youtube_id():
    yt_id = parse_youtube_id_from_viewer(SAMPLE_VIEWER_HTML)
    assert yt_id == "KlDL8qiVZuA"


def test_parse_youtube_id_missing():
    assert parse_youtube_id_from_viewer("<div>no iframe</div>") is None


def test_parse_empty_list():
    assert parse_video_list_html("") == []
