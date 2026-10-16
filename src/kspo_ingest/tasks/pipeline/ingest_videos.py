"""ingest_videos — 국민체력100 운동처방 동영상 파이프라인.

목록 크롤 → YouTube ID 추출 → 자막 추출 → 청킹 → 임베딩 → Qdrant 적재.
"""
from __future__ import annotations

import asyncio

from kspo_ingest.chunk.chunker import ChunkInput, chunk_page
from kspo_ingest.chunk.ids import to_qdrant_point_id
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
from kspo_ingest.settings import settings

log = get_logger("worker", "ingest_videos")

NFA_DOMAIN_HOST = "nfa.kspo.or.kr"
NFA_SOURCE_URL = "https://nfa.kspo.or.kr/classroom/program/selectPrescriptionMovieList.kspo"


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
    meta = (
        f"제목: {title}\n대상: {target_age} | 체력항목: {fitness_item}"
        f" | 운동도구: {equipment} | 부위: {body_part}"
    )
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
            await asyncio.sleep(0.5)
    finally:
        await client.aclose()

    all_videos = all_videos[:max_videos]
    log.bind(event="video_list_done", count=len(all_videos)).info("list crawled")

    # 2. YouTube ID 추출 + 자막 추출 + 청킹 + 임베딩
    client = await get_nfa_session()
    processed = 0
    skipped_no_caption = 0
    all_points: list[QdrantPoint] = []

    try:
        for video in all_videos:
            if not video.youtube_id:
                yt_id = await fetch_youtube_id(client, video.movie_sn)
                video.youtube_id = yt_id
                await asyncio.sleep(0.3)

            if not video.youtube_id:
                log.bind(event="video_no_yt_id", movie_sn=video.movie_sn).warning("no youtube id")
                continue

            caption = await fetch_caption(video.youtube_id)
            await asyncio.sleep(1.0)

            if not caption:
                skipped_no_caption += 1
                caption = ""

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
                    page_id=0,
                    embedding_version=settings.embedding_version,
                    domain_host=NFA_DOMAIN_HOST,
                    title=video.title,
                    posted_at=None,
                    summary=f"{video.target_age} 대상 {video.fitness_item} 운동",
                    body_text=synth_text,
                )
            )

            items = [
                ChunkToEmbed(chunk_id=i, text=c.text)
                for i, c in enumerate(chunks)
            ]
            async with session_factory() as s:
                embed_result = await embed_chunks(
                    s, items, model=settings.openai_embed_model, job_id=None,
                )

            for emb, chunk in zip(embed_result.embedded, chunks, strict=True):
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
                log.bind(
                    event="ingest_progress", processed=processed, total=len(all_videos)
                ).info("progress")
    finally:
        await client.aclose()

    # 3. Qdrant 일괄 upsert (100건씩 배치)
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
