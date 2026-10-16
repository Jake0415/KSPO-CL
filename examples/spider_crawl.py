"""Spider 크롤 예제 — Scrapy 스타일 비동기 스파이더."""
import asyncio

from kspo_ingest.crawl.spider import Spider, SpiderRequest, SpiderResponse


class KspoSpider(Spider):
    """KSPO 공지사항 크롤러."""

    name = "kspo_notice"
    start_urls = ["https://www.kspo.or.kr/"]

    async def parse(self, response: SpiderResponse):
        """메인 페이지에서 공지사항 링크 추출."""
        from selectolax.parser import HTMLParser

        tree = HTMLParser(response.html)

        # 공지사항 링크 추출
        for link in tree.css("a[href]"):
            href = link.attributes.get("href", "")
            text = link.text(strip=True)
            if not href or not text:
                continue

            yield {
                "url": response.url,
                "link_text": text[:100],
                "link_href": href[:200],
            }


async def main():
    spider = KspoSpider(
        concurrency=4,
        max_pages=5,  # 예제이므로 소수만
        max_depth=1,
    )

    items = []
    async for item in spider.crawl():
        items.append(item)

    print(f"\n총 {len(items)}개 항목 수집")
    stats = spider.stats
    print(f"요청: {stats.requests_sent}, 성공: {stats.responses_ok}, "
          f"에러: {stats.responses_error}, 시간: {stats.elapsed_seconds:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
