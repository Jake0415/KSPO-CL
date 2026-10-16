"""Stealth 브라우저 페칭 예제 — Cloudflare 등 봇 방어 대응."""
import asyncio

from kspo_ingest.crawl.browser import BrowserFetcher


async def main():
    fetcher = BrowserFetcher(
        default_profile="chrome_win",  # 스텔스 프로파일
        headless=True,
    )

    result = await fetcher.fetch("https://www.kspo.or.kr/")
    print(f"[{result.http_status}] {result.url}")
    print(f"Size: {len(result.raw_bytes)} bytes")
    print(f"Elapsed: {result.elapsed_ms}ms")

    # DOM 스냅샷 — 인터랙티브 요소 포함
    snapshot = await fetcher.get_dom_snapshot("https://www.kspo.or.kr/")
    print(f"\nTitle: {snapshot['title']}")
    print(f"Interactive elements: {len(snapshot['interactive_elements'])}")
    for el in snapshot["interactive_elements"][:5]:
        print(f"  [{el['tag']}] {el['text'][:50]} → {el['href'][:60]}")

    await fetcher.close()


if __name__ == "__main__":
    asyncio.run(main())
