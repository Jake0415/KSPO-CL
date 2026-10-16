"""YouTube 자막 추출 — timedtext API로 한국어 자동자막(ASR) 가져오기."""
from __future__ import annotations

import re

import httpx

from kspo_ingest.observability.logger import get_logger

log = get_logger("crawl", "youtube_caption")


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
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.split("\n")]
    return "\n".join(line for line in lines if line)


async def fetch_caption(video_id: str, *, lang: str = "ko") -> str | None:
    """YouTube 동영상의 자동자막을 가져온다."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={"Accept-Language": "ko-KR,ko;q=0.9"},
        )
        if resp.status_code != 200:
            log.bind(
                event="caption_page_error", video_id=video_id, status=resp.status_code
            ).warning("page fetch failed")
            return None

        match = re.search(r'"captionTracks":\[.*?"baseUrl":"(.*?)"', resp.text)
        if not match:
            log.bind(event="caption_no_tracks", video_id=video_id).info("no caption tracks found")
            return None

        base_url = match.group(1).replace("\\u0026", "&")
        if "lang=" not in base_url:
            base_url += f"&lang={lang}"
        if "fmt=" not in base_url:
            base_url += "&fmt=json3"
        else:
            base_url = re.sub(r"fmt=\w+", "fmt=json3", base_url)

        caption_resp = await client.get(base_url)
        if caption_resp.status_code != 200:
            log.bind(
                event="caption_fetch_error", video_id=video_id, status=caption_resp.status_code
            ).warning("caption fetch failed")
            return None

        data = caption_resp.json()
        text = parse_timedtext_json(data)
        if not text:
            return None

        log.bind(
            event="caption_ok", video_id=video_id, text_len=len(text)
        ).info("caption extracted")
        return text
