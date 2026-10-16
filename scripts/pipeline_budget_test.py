"""Pipeline Budget Test — $5 예산 내 전체 파이프라인 검증.

사이트별 대표 페이지를 크롤 → 파싱 → LLM Refine → 임베딩 추정 → 보고.

모드:
  dry_run  — LLM 호출 없이 토큰/비용 추정만
  mock     — 가짜 LLM 응답으로 파이프라인 전체 검증
  sample   — 대표 샘플만 실제 LLM 호출
  budget   — $5 한도 내 자동 범위 조정

실행:
  OPENAI_API_KEY=sk-... ADMIN_PASSWORD_BCRYPT='$2b$12$d' SESSION_SECRET=x \
  POSTGRES_USER=x POSTGRES_PASSWORD=x \
  .venv/bin/python scripts/pipeline_budget_test.py [--mode dry_run|mock|sample|budget]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from kspo_ingest.chunk.chunker import ChunkInput, chunk_page
from kspo_ingest.chunk.tokens import count_tokens
from kspo_ingest.clean.extractor import extract
from kspo_ingest.clean.hash import normalize_for_hash
from kspo_ingest.crawl.domain_profile import detect_js_redirect
from kspo_ingest.quality.budget import (
    BudgetReport,
    CallRecord,
    MOCK_REFINE_RESPONSE,
    ResponseCache,
    RunMode,
    estimate_embed_tokens,
    estimate_page_cost,
    estimate_refine_tokens,
    format_budget_report,
)
from kspo_ingest.quality.scorer import ScorerInput, score_document
from kspo_ingest.refine.cost import calc_cost_usd
from kspo_ingest.refine.prompts import SYSTEM_PROMPT, build_user_prompt
from kspo_ingest.refine.schema import REFINER_JSON_SCHEMA, RefinerOutput
from kspo_ingest.settings import settings

SITES = [
    {"host": "www.kspo.or.kr", "name": "KSPO 본사"},
    {"host": "www.sports.re.kr", "name": "한국스포츠정책과학원"},
    {"host": "www.ksponco.or.kr", "name": "한국체육산업개발"},
    {"host": "www.kcycle.or.kr", "name": "경륜"},
    {"host": "www.kboat.or.kr", "name": "경정"},
    {"host": "www.spoinfo.or.kr", "name": "체육시설알리미"},
    {"host": "www.parktel.co.kr", "name": "올림픽파크텔"},
    {"host": "nfa.kspo.or.kr", "name": "국민체력100"},
]

MAX_PAGES_PER_SITE = 3
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
TIMEOUT = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=5.0)
REFINE_MODEL = settings.openai_refine_model
EMBED_MODEL = settings.openai_embed_model


async def fetch_page(client: httpx.AsyncClient, url: str) -> dict | None:
    try:
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code >= 400:
            return None
        raw = resp.content
        if len(raw) < 2048:
            jt = detect_js_redirect(raw.decode("utf-8", "replace"), str(resp.url))
            if jt:
                resp = await client.get(jt, follow_redirects=True)
                raw = resp.content
        ct = resp.headers.get("content-type", "")
        if "html" not in ct.lower():
            return None
        result = extract(raw, ct)
        if not result.body_text or len(result.body_text) < 100:
            return None
        content_hash = normalize_for_hash(result.body_text)
        return {
            "url": str(resp.url),
            "title": result.title,
            "body_text": result.body_text,
            "method": result.method,
            "content_hash": content_hash,
        }
    except Exception:
        return None


def extract_links(html_bytes: bytes, host: str) -> list[str]:
    from selectolax.parser import HTMLParser
    html = html_bytes.decode("utf-8", errors="replace")
    tree = HTMLParser(html)
    seen: set[str] = set()
    out: list[str] = []
    skip_paths = ("/login", "/logout", "/signin", "/signup", "/mypage", "/member/login")
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        if href.startswith("/"):
            href = f"https://{host}{href}"
        parsed = urlparse(href)
        if parsed.netloc.lower() != host.lower():
            continue
        if any(seg in parsed.path.lower() for seg in skip_paths):
            continue
        key = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if key not in seen:
            seen.add(key)
            out.append(href)
    return out


async def call_refine_llm(
    title: str | None,
    body_text: str,
    *,
    mode: RunMode,
    cache: ResponseCache,
    content_hash: str,
    report: BudgetReport,
    url: str,
) -> dict | None:
    """LLM Refine 호출 (캐시/모드 대응)."""
    prompt_tokens, est_completion = estimate_refine_tokens(title, body_text)

    # 캐시 확인
    cached = cache.get(content_hash, "refine")
    if cached is not None:
        cost = float(calc_cost_usd(REFINE_MODEL, 0, 0))
        report.add_call(CallRecord(
            url=url, content_hash=content_hash, purpose="refine",
            model=REFINE_MODEL, prompt_tokens=0, completion_tokens=0,
            cost_usd=0.0, cached=True, mock=False,
        ))
        return cached

    # DRY RUN — 비용 추정만
    if mode == RunMode.DRY_RUN:
        cost = float(calc_cost_usd(REFINE_MODEL, prompt_tokens, est_completion))
        report.add_call(CallRecord(
            url=url, content_hash=content_hash, purpose="refine",
            model=REFINE_MODEL, prompt_tokens=prompt_tokens,
            completion_tokens=est_completion, cost_usd=cost,
            cached=False, mock=True,
        ))
        return MOCK_REFINE_RESPONSE

    # MOCK — 가짜 응답
    if mode == RunMode.MOCK:
        cost = float(calc_cost_usd(REFINE_MODEL, prompt_tokens, est_completion))
        report.add_call(CallRecord(
            url=url, content_hash=content_hash, purpose="refine",
            model=REFINE_MODEL, prompt_tokens=prompt_tokens,
            completion_tokens=est_completion, cost_usd=cost,
            cached=False, mock=True,
        ))
        cache.put(content_hash, "refine", MOCK_REFINE_RESPONSE)
        return MOCK_REFINE_RESPONSE

    # 예산 확인
    est_cost = float(calc_cost_usd(REFINE_MODEL, prompt_tokens, est_completion))
    if mode == RunMode.BUDGET and report.total_cost_usd + est_cost > report.budget_usd:
        report.documents_skipped += 1
        return None

    # LIVE / SAMPLE / BUDGET — 실제 LLM 호출
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=60.0)

    try:
        t0 = time.perf_counter()
        response = await client.chat.completions.create(
            model=REFINE_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(title, body_text)},
            ],
            response_format={"type": "json_schema", "json_schema": REFINER_JSON_SCHEMA},
            temperature=0.0,
        )
        elapsed = int((time.perf_counter() - t0) * 1000)

        raw = response.choices[0].message.content or "{}"
        result = json.loads(raw)
        actual_prompt = response.usage.prompt_tokens
        actual_completion = response.usage.completion_tokens
        actual_cost = float(calc_cost_usd(REFINE_MODEL, actual_prompt, actual_completion))

        report.add_call(CallRecord(
            url=url, content_hash=content_hash, purpose="refine",
            model=REFINE_MODEL, prompt_tokens=actual_prompt,
            completion_tokens=actual_completion, cost_usd=actual_cost,
            cached=False, mock=False, elapsed_ms=elapsed,
        ))

        cache.put(content_hash, "refine", result)
        return result

    except Exception as e:
        report.add_call(CallRecord(
            url=url, content_hash=content_hash, purpose="refine",
            model=REFINE_MODEL, prompt_tokens=prompt_tokens,
            completion_tokens=0, cost_usd=0.0,
            cached=False, mock=False, success=False, error=str(e)[:100],
        ))
        return None


async def process_page(
    page_data: dict,
    *,
    mode: RunMode,
    cache: ResponseCache,
    report: BudgetReport,
    host: str,
) -> dict:
    """단일 페이지 파이프라인 실행."""
    url = page_data["url"]
    title = page_data["title"]
    body_text = page_data["body_text"]
    content_hash = page_data["content_hash"]

    result: dict = {
        "url": url,
        "title": title,
        "body_length": len(body_text),
        "content_hash": content_hash[:12],
        "extraction_method": page_data["method"],
    }

    # 1. LLM Refine
    refine_result = await call_refine_llm(
        title, body_text,
        mode=mode, cache=cache, content_hash=content_hash,
        report=report, url=url,
    )

    if refine_result is None:
        result["refine_ok"] = False
        result["summary"] = None
        result["keywords"] = []
        report.documents_tested += 1
        return result

    result["refine_ok"] = True
    result["summary"] = (refine_result.get("summary") or "")[:80]
    result["keywords"] = refine_result.get("keywords", [])
    result["is_meaningful"] = refine_result.get("is_meaningful", True)

    # 2. Chunking (추정)
    chunks = chunk_page(ChunkInput(
        page_id=0, embedding_version=1,
        domain_host=host, title=title,
        posted_at=None, summary=result["summary"],
        body_text=refine_result.get("refined_text", body_text),
    ))
    result["chunk_count"] = len(chunks)
    result["chunk_tokens"] = sum(c.token_len for c in chunks)

    # 3. Embedding 비용 추정
    embed_tokens = sum(c.token_len for c in chunks)
    embed_cost = float(calc_cost_usd(EMBED_MODEL, embed_tokens, 0))
    report.add_call(CallRecord(
        url=url, content_hash=content_hash, purpose="embedding",
        model=EMBED_MODEL, prompt_tokens=embed_tokens,
        completion_tokens=0, cost_usd=embed_cost,
        cached=False, mock=(mode != RunMode.LIVE),
    ))
    result["embed_cost_usd"] = embed_cost

    # 4. Quality scoring
    score = score_document(ScorerInput(
        title=title, body_text=body_text,
        extraction_method=page_data["method"],
        posted_at=None, summary=result["summary"],
        keywords=result["keywords"],
        is_meaningful=result["is_meaningful"],
        domain_host=host,
    ))
    result["quality_score"] = score.quality_score
    result["quadrant"] = score.quadrant

    report.documents_tested += 1
    return result


async def test_site(
    site: dict,
    *,
    mode: RunMode,
    cache: ResponseCache,
    report: BudgetReport,
) -> list[dict]:
    host = site["host"]
    print(f"\n[{site['name']}] ({host})")

    results: list[dict] = []

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True, http2=True,
        headers={"User-Agent": UA},
    ) as client:
        # Root
        root_url = f"https://{host}/"
        root_resp = await client.get(root_url, follow_redirects=True)
        raw = root_resp.content
        if len(raw) < 2048:
            jt = detect_js_redirect(raw.decode("utf-8", "replace"), str(root_resp.url))
            if jt:
                root_resp = await client.get(jt, follow_redirects=True)
                raw = root_resp.content

        root_data = await fetch_page(client, root_url)
        if root_data:
            r = await process_page(root_data, mode=mode, cache=cache, report=report, host=host)
            results.append(r)
            _print_result(r)

        # 내부 링크 샘플
        links = extract_links(raw, host)
        for link_url in links[:MAX_PAGES_PER_SITE - 1]:
            # 예산 확인
            if mode == RunMode.BUDGET and report.total_cost_usd >= report.budget_usd * 0.95:
                print(f"  ⚠️ 예산 95% 도달 — 중단")
                break

            data = await fetch_page(client, link_url)
            if data is None:
                continue

            # content_hash 중복 확인
            existing = [r for r in results if r.get("content_hash") == data["content_hash"][:12]]
            if existing:
                print(f"  ↺ SKIP (중복 content_hash) {link_url[:60]}")
                report.documents_skipped += 1
                continue

            r = await process_page(data, mode=mode, cache=cache, report=report, host=host)
            results.append(r)
            _print_result(r)

    # 사이트 비용 집계
    site_cost = sum(
        c.cost_usd for c in report.calls
        if any(host in c.url for _ in [1])
    )
    report.site_costs[host] = site_cost

    return results


def _print_result(r: dict) -> None:
    refine = "✅" if r.get("refine_ok") else "❌"
    q = r.get("quadrant", "?")
    qs = r.get("quality_score", 0)
    summary = (r.get("summary") or "")[:40]
    kw_count = len(r.get("keywords", []))
    chunks = r.get("chunk_count", 0)
    print(f"  {refine} [{q}:{qs:.2f}] {r['url'][:55]}")
    print(f"    body={r['body_length']}자 chunks={chunks} kw={kw_count} summary=\"{summary}\"")


async def main():
    parser = argparse.ArgumentParser(description="Pipeline Budget Test")
    parser.add_argument("--mode", default="dry_run", choices=[m.value for m in RunMode])
    parser.add_argument("--budget", type=float, default=5.0)
    parser.add_argument("--cache-dir", default="/tmp/kspo_llm_cache")
    args = parser.parse_args()

    mode = RunMode(args.mode)
    cache = ResponseCache(Path(args.cache_dir))
    report = BudgetReport(mode=mode.value, budget_usd=args.budget)

    print("=" * 60)
    print(f"  Pipeline Budget Test — {mode.value} mode")
    print(f"  Budget: ${args.budget:.2f}")
    print(f"  Sites: {len(SITES)}  Pages/site: {MAX_PAGES_PER_SITE}")
    print(f"  Cache: {cache.size} entries loaded")
    print("=" * 60)

    all_results: list[dict] = []
    for site in SITES:
        results = await test_site(site, mode=mode, cache=cache, report=report)
        all_results.extend(results)

    # 리포트
    print("\n" + format_budget_report(report))

    # 문서별 상세 요약
    print("\nDocument Summary:")
    print(f"{'URL':<55} {'Q':>3} {'Score':>5} {'Chunks':>6} {'KW':>3} {'Refine':>6}")
    print("-" * 85)
    for r in all_results:
        q = r.get("quadrant", "?")
        print(f"  {r['url'][:53]:<53} {q:>3} {r.get('quality_score',0):>5.2f} "
              f"{r.get('chunk_count',0):>6} {len(r.get('keywords',[])):>3} "
              f"{'OK' if r.get('refine_ok') else 'FAIL':>6}")


if __name__ == "__main__":
    asyncio.run(main())
