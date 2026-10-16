"""기본 HTTP 페칭 예제 — 커넥션 풀 재사용."""
import asyncio

from kspo_ingest.crawl.fetcher import Fetcher


async def main():
    fetcher = Fetcher()

    # 같은 호스트에 여러 요청 — 커넥션 풀 재사용
    urls = [
        "https://www.kspo.or.kr/",
        "https://www.kspo.or.kr/kspo/main/main.do",
    ]

    for url in urls:
        result = await fetcher.fetch(url, user_agent="kspo-ingest/0.2")
        print(f"[{result.http_status}] {result.url} ({len(result.raw_bytes)} bytes, {result.elapsed_ms}ms)")

    await fetcher.close()


if __name__ == "__main__":
    asyncio.run(main())
