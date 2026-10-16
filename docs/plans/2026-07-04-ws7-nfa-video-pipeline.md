# WS7: 국민체력100 운동처방 동영상 파이프라인 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pipeline that crawls 699 exercise prescription videos from nfa.kspo.or.kr, extracts YouTube captions, and indexes them into Qdrant with structured metadata for chatbot Q&A.

**Architecture:** Three new modules: (1) `nfa_video.py` crawls the video list pages and extracts YouTube IDs, (2) `youtube_caption.py` fetches Korean auto-captions via YouTube's timedtext API, (3) `ingest_videos.py` orchestrates the full pipeline using existing chunker/embedder/adapter. Videos are stored as `type: exercise_video` with rich metadata tags (target age, fitness item, equipment, body part, disease).

**Tech Stack:** Python 3.12, httpx, selectolax, Playwright (session cookie), existing kspo-ingest pipeline (chunker, embedder, Qdrant adapter)

---

## File Structure

| File | Status | Purpose |
|------|--------|---------|
| `src/kspo_ingest/crawl/nfa_video.py` | **Create** | Session cookie acquisition, video list pagination, metadata parsing, YouTube ID extraction |
| `src/kspo_ingest/crawl/youtube_caption.py` | **Create** | Fetch YouTube auto-captions via timedtext API |
| `src/kspo_ingest/tasks/pipeline/ingest_videos.py` | **Create** | Pipeline orchestration: list → captions → chunk → embed → upsert |
| `src/kspo_ingest/api/routers/jobs.py` | **Modify** | Add POST /api/jobs/ingest-videos endpoint |
| `tests/test_nfa_video.py` | **Create** | Video list parsing + YouTube ID extraction tests |
| `tests/test_youtube_caption.py` | **Create** | Caption extraction tests |
| `tests/test_ingest_videos.py` | **Create** | Pipeline integration tests |

---

### Task 1: YouTube Caption Extractor

**Files:**
- Create: `src/kspo_ingest/crawl/youtube_caption.py`
- Create: `tests/test_youtube_caption.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_youtube_caption.py
from __future__ import annotations

import json

import pytest

from kspo_ingest.crawl.youtube_caption import (
    extract_caption_text,
    parse_timedtext_json,
)


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


def test_extract_caption_text_formats_cleanly():
    text = parse_timedtext_json(SAMPLE_TIMEDTEXT)
    lines = [l for l in text.split("\n") if l.strip()]
    assert len(lines) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/yeonsu/2026/kspo/kspo-ingest && uv run pytest tests/test_youtube_caption.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement youtube_caption.py**

```python
# src/kspo_ingest/crawl/youtube_caption.py
"""YouTube 자막 추출 — timedtext API로 한국어 자동자막(ASR) 가져오기."""
from __future__ import annotations

import re

import httpx

from kspo_ingest.observability.logger import get_logger

log = get_logger("crawl", "youtube_caption")

_TIMEDTEXT_URL = "https://www.youtube.com/api/timedtext"


def parse_timedtext_json(data: dict) -> str:
    """YouTube timedtext JSON3 응답을 평문 텍스트로 변환."""
    parts: list[str] = []
    for event in data.get("events", []):
        segs = event.get("segs")
        if not segs:
            continue
        for seg in segs:
            text = seg.get("utf8", "")
            if text:
                parts.append(text)
    raw = "".join(parts)
    # 연속 공백 정리, 빈 줄 제거
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.split("\n")]
    return "\n".join(line for line in lines if line)


async def fetch_caption(video_id: str, *, lang: str = "ko") -> str | None:
    """YouTube 동영상의 자동자막을 가져온다.

    1. 동영상 페이지에서 timedtext URL 추출
    2. JSON3 포맷으로 자막 다운로드
    3. 평문 텍스트로 변환
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 동영상 페이지에서 captionTracks 추출
        resp = await client.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={"Accept-Language": "ko-KR,ko;q=0.9"},
        )
        if resp.status_code != 200:
            log.bind(event="caption_page_error", video_id=video_id, status=resp.status_code).warning("page fetch failed")
            return None

        # timedtext base URL 추출
        match = re.search(r'"captionTracks":\[.*?"baseUrl":"(.*?)"', resp.text)
        if not match:
            log.bind(event="caption_no_tracks", video_id=video_id).info("no caption tracks found")
            return None

        base_url = match.group(1).replace("\\u0026", "&")

        # JSON3 포맷으로 자막 요청
        if "lang=" not in base_url:
            base_url += f"&lang={lang}"
        if "fmt=" not in base_url:
            base_url += "&fmt=json3"
        else:
            base_url = re.sub(r"fmt=\w+", "fmt=json3", base_url)

        caption_resp = await client.get(base_url)
        if caption_resp.status_code != 200:
            log.bind(event="caption_fetch_error", video_id=video_id, status=caption_resp.status_code).warning("caption fetch failed")
            return None

        data = caption_resp.json()
        text = parse_timedtext_json(data)
        if not text:
            return None

        log.bind(event="caption_ok", video_id=video_id, text_len=len(text)).info("caption extracted")
        return text
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/yeonsu/2026/kspo/kspo-ingest && uv run pytest tests/test_youtube_caption.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/yeonsu/2026/kspo/kspo-ingest
git add src/kspo_ingest/crawl/youtube_caption.py tests/test_youtube_caption.py
git commit -m "feat: add YouTube caption extractor (timedtext JSON3 parser)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: NFA Video List Crawler

**Files:**
- Create: `src/kspo_ingest/crawl/nfa_video.py`
- Create: `tests/test_nfa_video.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_nfa_video.py
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/yeonsu/2026/kspo/kspo-ingest && uv run pytest tests/test_nfa_video.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement nfa_video.py**

```python
# src/kspo_ingest/crawl/nfa_video.py
"""국민체력100 운동처방 동영상 목록 크롤 + YouTube ID 추출."""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
from selectolax.parser import HTMLParser

from kspo_ingest.observability.logger import get_logger

log = get_logger("crawl", "nfa_video")

NFA_BASE = "https://nfa.kspo.or.kr"
BEFORE_RESERVE_URL = f"{NFA_BASE}/beforeReserve.kspo"
MOVIE_LIST_URL = f"{NFA_BASE}/classroom/program/selectPrescriptionMovieList.kspo"
MOVIE_VIEW_URL = f"{NFA_BASE}/classroom/program/selectPrescriptionMovieViewJs.kspo"


@dataclass
class VideoMeta:
    movie_sn: str
    title: str
    fitness_item: str
    equipment: str
    body_part: str
    target_age: str
    disease: str | None = None
    youtube_id: str | None = None


def parse_video_list_html(html: str) -> list[VideoMeta]:
    """동영상 목록 페이지 HTML에서 VideoMeta 리스트 추출."""
    if not html:
        return []
    tree = HTMLParser(html)
    videos: list[VideoMeta] = []

    for li in tree.css("button[onclick*='fnMovieViewerOpen']"):
        onclick = li.attributes.get("onclick", "")
        sn_match = re.search(r'fnMovieViewerOpen\("(\d+)"', onclick)
        if not sn_match:
            continue
        movie_sn = sn_match.group(1)

        title_node = li.css_first(".tit, span")
        title = title_node.text(strip=True) if title_node else ""

        # 부모 li에서 메타데이터 추출
        parent = li.parent
        if parent is None:
            continue
        dd_nodes = parent.css("dl dd, .infoArea dd, dd")
        meta_values = [dd.text(strip=True) for dd in dd_nodes]

        videos.append(VideoMeta(
            movie_sn=movie_sn,
            title=title,
            fitness_item=meta_values[0] if len(meta_values) > 0 else "",
            equipment=meta_values[1] if len(meta_values) > 1 else "",
            body_part=meta_values[2] if len(meta_values) > 2 else "",
            target_age=meta_values[3] if len(meta_values) > 3 else "",
        ))

    return videos


def parse_youtube_id_from_viewer(html: str) -> str | None:
    """동영상 뷰어 응답 HTML에서 YouTube video ID 추출."""
    match = re.search(r'youtube\.com/embed/([a-zA-Z0-9_-]+)', html)
    return match.group(1) if match else None


async def get_nfa_session() -> httpx.AsyncClient:
    """nfa.kspo.or.kr 세션 쿠키 확보. beforeReserve 방문으로 JSESSIONID 획득."""
    client = httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
    )
    await client.get(BEFORE_RESERVE_URL)
    log.bind(event="nfa_session_ok").info("session cookie acquired")
    return client


async def fetch_video_list_page(client: httpx.AsyncClient, page_num: int) -> str:
    """동영상 목록 N페이지 조회. POST with pageNo."""
    resp = await client.post(
        MOVIE_LIST_URL,
        data={"menuId": "A03_B05", "pageNo": str(page_num)},
    )
    return resp.text


async def fetch_youtube_id(client: httpx.AsyncClient, movie_sn: str) -> str | None:
    """movieSn으로 동영상 뷰어 HTML 조회 → YouTube ID 추출."""
    resp = await client.post(
        MOVIE_VIEW_URL,
        data={"movieSn": movie_sn, "popNm": "movieViewer"},
    )
    return parse_youtube_id_from_viewer(resp.text)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/yeonsu/2026/kspo/kspo-ingest && uv run pytest tests/test_nfa_video.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/yeonsu/2026/kspo/kspo-ingest
git add src/kspo_ingest/crawl/nfa_video.py tests/test_nfa_video.py
git commit -m "feat: add NFA video list crawler + YouTube ID extraction

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Video Ingestion Pipeline

**Files:**
- Create: `src/kspo_ingest/tasks/pipeline/ingest_videos.py`
- Create: `tests/test_ingest_videos.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_ingest_videos.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kspo_ingest.tasks.pipeline.ingest_videos import build_video_chunk_text, VideoChunkInput


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
    assert "자막 없음" in text or len(text) > 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/yeonsu/2026/kspo/kspo-ingest && uv run pytest tests/test_ingest_videos.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement ingest_videos.py**

```python
# src/kspo_ingest/tasks/pipeline/ingest_videos.py
"""ingest_videos — 국민체력100 운동처방 동영상 파이프라인.

목록 크롤 → YouTube ID 추출 → 자막 추출 → 청킹 → 임베딩 → Qdrant 적재.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from kspo_ingest.chunk.chunker import ChunkInput, chunk_page
from kspo_ingest.chunk.ids import chunk_id_sha1, to_qdrant_point_id
from kspo_ingest.crawl.nfa_video import (
    VideoMeta,
    fetch_video_list_page,
    fetch_youtube_id,
    get_nfa_session,
    parse_video_list_html,
)
from kspo_ingest.crawl.youtube_caption import fetch_caption
from kspo_ingest.embed.embedder import ChunkToEmbed, embed_chunks
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.qdrant.adapter import QdrantDirectAdapter, QdrantPoint
from kspo_ingest.qdrant.payload import PayloadInput, build_payload
from kspo_ingest.settings import settings

log = get_logger("worker", "ingest_videos")

NFA_DOMAIN_HOST = "nfa.kspo.or.kr"
NFA_SOURCE_URL = "https://nfa.kspo.or.kr/classroom/program/selectPrescriptionMovieList.kspo"


@dataclass
class VideoChunkInput:
    movie_sn: str
    title: str
    target_age: str
    fitness_item: str
    equipment: str
    body_part: str
    disease: str | None
    youtube_id: str
    caption_text: str


def build_video_chunk_text(
    *,
    title: str,
    target_age: str,
    fitness_item: str,
    equipment: str,
    body_part: str,
    caption_text: str,
) -> str:
    """메타데이터 + 자막을 합성한 청크 텍스트 생성."""
    header = f"[국민체력100 운동처방 | {NFA_DOMAIN_HOST}]"
    meta = f"제목: {title}\n대상: {target_age} | 체력항목: {fitness_item} | 운동도구: {equipment} | 부위: {body_part}"
    body = caption_text if caption_text else "(자막 없음)"
    return f"{header}\n{meta}\n---\n{body}"


async def ingest_videos(ctx: dict, *, max_videos: int = 699) -> dict:
    """전체 동영상 파이프라인 실행."""
    session_factory = ctx["session_factory"]

    # 1. 세션 확보 + 목록 크롤
    log.bind(event="ingest_videos_start", max_videos=max_videos).info("starting")
    client = await get_nfa_session()

    all_videos: list[VideoMeta] = []
    page_num = 1
    try:
        while len(all_videos) < max_videos:
            html = await fetch_video_list_page(client, page_num)
            videos = parse_video_list_html(html)
            if not videos:
                break
            all_videos.extend(videos)
            page_num += 1
            await asyncio.sleep(0.5)  # rate limit
    finally:
        await client.aclose()

    all_videos = all_videos[:max_videos]
    log.bind(event="video_list_done", count=len(all_videos)).info("list crawled")

    # 2. YouTube ID 추출 + 자막 추출
    client = await get_nfa_session()
    processed = 0
    skipped_no_caption = 0
    all_points: list[QdrantPoint] = []

    try:
        for video in all_videos:
            # YouTube ID
            if not video.youtube_id:
                yt_id = await fetch_youtube_id(client, video.movie_sn)
                video.youtube_id = yt_id
                await asyncio.sleep(0.3)

            if not video.youtube_id:
                log.bind(event="video_no_yt_id", movie_sn=video.movie_sn).warning("no youtube id")
                continue

            # 자막 추출
            caption = await fetch_caption(video.youtube_id)
            await asyncio.sleep(1.0)  # YouTube rate limit

            if not caption:
                skipped_no_caption += 1
                caption = ""

            # 3. 합성 텍스트 → 청킹
            synth_text = build_video_chunk_text(
                title=video.title,
                target_age=video.target_age,
                fitness_item=video.fitness_item,
                equipment=video.equipment,
                body_part=video.body_part,
                caption_text=caption,
            )

            chunks = chunk_page(
                ChunkInput(
                    page_id=0,  # 동영상은 Page 테이블 미사용
                    embedding_version=settings.embedding_version,
                    domain_host=NFA_DOMAIN_HOST,
                    title=video.title,
                    posted_at=None,
                    summary=f"{video.target_age} 대상 {video.fitness_item} 운동",
                    body_text=synth_text,
                )
            )

            # 4. 임베딩
            items = [
                ChunkToEmbed(chunk_id=i, text=c.text)
                for i, c in enumerate(chunks)
            ]
            async with session_factory() as s:
                embed_result = await embed_chunks(
                    s, items, model=settings.openai_embed_model, job_id=None,
                )

            # 5. Payload + Qdrant 포인트 구성
            for emb, chunk in zip(embed_result.embedded, chunks):
                vid_chunk_id = f"nfa-video-{video.movie_sn}-{chunk.chunk_index}"
                point_id = to_qdrant_point_id(vid_chunk_id)
                tags = [
                    f"d:{NFA_DOMAIN_HOST}",
                    f"t:{video.target_age}",
                    f"f:{video.fitness_item}",
                    "type:exercise_video",
                    f"v:{settings.embedding_version}",
                ]
                payload = {
                    "page_content": chunk.text,
                    "metadata": {
                        "id": vid_chunk_id,
                        "source": NFA_SOURCE_URL,
                        "namespace": settings.kb_namespace,
                        "type": "exercise_video",
                        "domain_host": NFA_DOMAIN_HOST,
                        "title": video.title,
                        "youtube_id": video.youtube_id,
                        "youtube_url": f"https://www.youtube.com/watch?v={video.youtube_id}",
                        "target_age": video.target_age,
                        "fitness_item": video.fitness_item,
                        "equipment": video.equipment,
                        "body_part": video.body_part,
                        "disease": video.disease,
                        "embedding_version": settings.embedding_version,
                        "tags": tags,
                    },
                }
                all_points.append(QdrantPoint(
                    qdrant_point_id=point_id,
                    vector=emb.vector,
                    payload=payload,
                ))

            processed += 1
            if processed % 10 == 0:
                log.bind(event="ingest_progress", processed=processed, total=len(all_videos)).info("progress")
    finally:
        await client.aclose()

    # 6. Qdrant 일괄 upsert (100건씩 배치)
    adapter = QdrantDirectAdapter()
    upserted = 0
    for i in range(0, len(all_points), 100):
        batch = all_points[i:i + 100]
        result = await adapter.upsert_chunks(batch)
        upserted += result.upserted

    log.bind(
        event="ingest_videos_done",
        processed=processed,
        skipped_no_caption=skipped_no_caption,
        points=upserted,
    ).info("done")

    return {
        "videos_crawled": len(all_videos),
        "videos_processed": processed,
        "skipped_no_caption": skipped_no_caption,
        "points_upserted": upserted,
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/yeonsu/2026/kspo/kspo-ingest && uv run pytest tests/test_ingest_videos.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/yeonsu/2026/kspo/kspo-ingest
git add src/kspo_ingest/tasks/pipeline/ingest_videos.py tests/test_ingest_videos.py
git commit -m "feat: add video ingestion pipeline (list → caption → chunk → embed → upsert)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: API Endpoint + Worker Registration

**Files:**
- Modify: `src/kspo_ingest/api/routers/jobs.py`
- Modify: `src/kspo_ingest/tasks/worker.py`

- [ ] **Step 1: Read current jobs.py to understand patterns**

```bash
cd /Users/yeonsu/2026/kspo/kspo-ingest
# Read src/kspo_ingest/api/routers/jobs.py
```

- [ ] **Step 2: Add ingest-videos endpoint to jobs.py**

Add at the end of the router, following existing endpoint patterns:

```python
from kspo_ingest.tasks.pipeline.ingest_videos import ingest_videos

class IngestVideosRequest(BaseModel):
    max_videos: int = Field(default=699, ge=1, le=699)


@router.post("/ingest-videos", status_code=status.HTTP_202_ACCEPTED)
async def trigger_ingest_videos(
    body: IngestVideosRequest,
    _admin: str = AdminDep,
) -> dict:
    """국민체력100 운동처방 동영상 파이프라인 수동 트리거."""
    pool = await _get_pool()
    arq_job = await pool.enqueue_job("ingest_videos", max_videos=body.max_videos)
    return {"job_id": arq_job.job_id if arq_job else None, "max_videos": body.max_videos}
```

- [ ] **Step 3: Register ingest_videos in worker.py**

Add import and function registration:

```python
from kspo_ingest.tasks.pipeline.ingest_videos import ingest_videos
```

Add `ingest_videos` to the `functions` list in `WorkerSettings`.

- [ ] **Step 4: Run full test suite**

```bash
cd /Users/yeonsu/2026/kspo/kspo-ingest && uv run pytest -x -q --ignore=tests/test_auth.py --ignore=tests/test_clean_hash.py --ignore=tests/test_encoding.py
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/yeonsu/2026/kspo/kspo-ingest
git add src/kspo_ingest/api/routers/jobs.py src/kspo_ingest/tasks/worker.py
git commit -m "feat: add POST /api/jobs/ingest-videos endpoint + worker registration

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Post-Completion

WS7 delivers:
- YouTube caption extraction from timedtext API (no STT cost)
- NFA video list crawler with session cookie handling + pagination
- Full pipeline: list → YouTube ID → caption → chunk → embed → Qdrant upsert
- API trigger endpoint for manual/automated execution
- Structured metadata tags for filtered search (target age, fitness item, equipment, body part)

The same `POST /api/qa` endpoint handles video queries — Qdrant search returns exercise_video type results with YouTube URLs for reference.
