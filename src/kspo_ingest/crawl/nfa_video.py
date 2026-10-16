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

    for btn in tree.css("button[onclick*='fnMovieViewerOpen']"):
        onclick = btn.attributes.get("onclick", "")
        sn_match = re.search(r'fnMovieViewerOpen\("(\d+)"', onclick)
        if not sn_match:
            continue
        movie_sn = sn_match.group(1)

        title_node = btn.css_first(".tit, span")
        title = title_node.text(strip=True) if title_node else ""

        parent = btn.parent
        if parent is None:
            continue
        dd_nodes = parent.css("dd")
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
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        },
    )
    await client.get(BEFORE_RESERVE_URL)
    log.bind(event="nfa_session_ok").info("session cookie acquired")
    return client


async def fetch_video_list_page(client: httpx.AsyncClient, page_num: int) -> str:
    """동영상 목록 N페이지 조회."""
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
