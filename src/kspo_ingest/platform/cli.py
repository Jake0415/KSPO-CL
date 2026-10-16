"""CLI — Typer 기반 명령줄 인터페이스.

사용법:
    # 단일 URL 크롤
    python -m kspo_ingest.platform.cli fetch https://example.com

    # Spider 실행
    python -m kspo_ingest.platform.cli spider --start-url https://example.com --max-pages 100

    # AI Agent 실행
    python -m kspo_ingest.platform.cli agent "KSPO 홈페이지에서 공지사항 추출"

    # 프록시 헬스체크
    python -m kspo_ingest.platform.cli proxy-check

    # 메트릭 확인
    python -m kspo_ingest.platform.cli metrics
"""
from __future__ import annotations

import asyncio
import json

import anyio

try:
    import typer
except ImportError:
    typer = None  # type: ignore[assignment]

from kspo_ingest.observability.logger import get_logger

log = get_logger("platform", "cli")


def _create_app() -> typer.Typer:  # type: ignore[name-defined]
    if typer is None:
        raise ImportError("typer is required for CLI: pip install typer")

    app = typer.Typer(
        name="kspo-ingest",
        help="KSPO Web Crawling & AI Automation CLI",
    )

    @app.command()
    def fetch(
        url: str = typer.Argument(..., help="URL to fetch"),
        playwright: bool = typer.Option(False, "--playwright", "-p", help="Use Playwright"),
        stealth: str | None = typer.Option(None, "--stealth", "-s", help="Stealth profile"),
        output: str | None = typer.Option(None, "--output", "-o", help="Output file"),
    ) -> None:
        """Fetch a single URL and display the result."""

        async def _run() -> None:
            if playwright:
                from kspo_ingest.crawl.browser import BrowserFetcher

                fetcher = BrowserFetcher(
                    default_profile=stealth,
                    headless=True,
                )
                result = await fetcher.fetch(url)
                await fetcher.close()
            else:
                from kspo_ingest.crawl.fetcher import Fetcher

                fetcher = Fetcher()
                ua = "kspo-ingest/0.2 CLI"
                result = await fetcher.fetch(url, user_agent=ua)
                await fetcher.close()

            typer.echo(f"URL: {result.url}")
            typer.echo(f"Status: {result.http_status}")
            typer.echo(f"Content-Type: {result.content_type}")
            typer.echo(f"Size: {len(result.raw_bytes)} bytes")
            typer.echo(f"Elapsed: {result.elapsed_ms}ms")

            if output:
                await anyio.Path(output).write_bytes(result.raw_bytes)
                typer.echo(f"Saved to: {output}")

        asyncio.run(_run())

    @app.command()
    def spider(
        start_url: str = typer.Option(..., "--start-url", "-u", help="Starting URL"),
        max_pages: int = typer.Option(100, "--max-pages", "-n", help="Max pages to crawl"),
        concurrency: int = typer.Option(4, "--concurrency", "-c", help="Concurrent workers"),
        max_depth: int = typer.Option(5, "--max-depth", "-d", help="Max crawl depth"),
        output: str | None = typer.Option(None, "--output", "-o", help="Output JSONL file"),
    ) -> None:
        """Run a spider crawl starting from the given URL."""

        async def _run() -> None:
            from kspo_ingest.crawl.spider import Spider

            class CliSpider(Spider):
                name = "cli"
                start_urls = [start_url]

            spider = CliSpider(
                concurrency=concurrency,
                max_pages=max_pages,
                max_depth=max_depth,
            )

            items: list[dict] = []
            async for item in spider.crawl():
                items.append(item)
                typer.echo(f"[{len(items)}] {json.dumps(item, ensure_ascii=False)[:120]}")

            if output:
                content = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items)
                await anyio.Path(output).write_text(content, encoding="utf-8")
                typer.echo(f"\nSaved {len(items)} items to {output}")

            stats = spider.stats
            typer.echo(f"\nStats: {stats.requests_sent} requests, "
                       f"{stats.responses_ok} ok, {stats.responses_error} errors, "
                       f"{stats.items_yielded} items, "
                       f"{stats.elapsed_seconds:.1f}s elapsed, "
                       f"{stats.requests_per_second:.1f} req/s")

        asyncio.run(_run())

    @app.command()
    def agent(
        task: str = typer.Argument(..., help="Natural language task description"),
        headless: bool = typer.Option(True, "--headless/--no-headless", help="Headless browser"),
        max_steps: int = typer.Option(30, "--max-steps", "-n", help="Max agent steps"),
        stealth: str | None = typer.Option(None, "--stealth", "-s", help="Stealth profile"),
    ) -> None:
        """Run an AI agent to complete a browser task."""

        async def _run() -> None:
            from kspo_ingest.agent.agent import Agent, AgentConfig

            config = AgentConfig(
                max_steps=max_steps,
                headless=headless,
                stealth_profile=stealth,
            )
            ag = Agent(task=task, config=config)
            result = await ag.run()
            await ag.close()

            typer.echo(f"\nTask: {result.task}")
            typer.echo(f"Success: {result.success}")
            typer.echo(f"Result: {result.result}")
            typer.echo(f"Steps: {result.steps_taken}")
            typer.echo(f"Elapsed: {result.elapsed_ms}ms")
            if result.errors:
                typer.echo(f"Errors: {result.errors}")
            if result.extracted_data:
                typer.echo(
                    f"Data: {json.dumps(result.extracted_data, ensure_ascii=False, indent=2)}"
                )

        asyncio.run(_run())

    @app.command(name="proxy-check")
    def proxy_check(
        proxies: str = typer.Argument(..., help="Comma-separated proxy URLs"),
    ) -> None:
        """Check proxy health."""

        async def _run() -> None:
            from kspo_ingest.crawl.proxy import ProxyRotator

            urls = [p.strip() for p in proxies.split(",") if p.strip()]
            rotator = ProxyRotator(urls)
            results = await rotator.health_check_all()
            for url, healthy in results.items():
                status = "HEALTHY" if healthy else "UNHEALTHY"
                typer.echo(f"  {status}: {url}")

        asyncio.run(_run())

    @app.command()
    def metrics() -> None:
        """Display current metrics."""
        from kspo_ingest.platform.metrics import get_metrics_text

        typer.echo(get_metrics_text())

    @app.command()
    def selector(
        url: str = typer.Argument(..., help="URL to fetch"),
        css: str = typer.Argument(..., help="CSS selector to test"),
        adaptive: bool = typer.Option(True, "--adaptive/--no-adaptive", help="Use adaptive"),
    ) -> None:
        """Test an adaptive CSS selector against a URL."""

        async def _run() -> None:
            from kspo_ingest.crawl.fetcher import Fetcher
            from kspo_ingest.crawl.selector import AdaptiveSelector

            fetcher = Fetcher()
            result = await fetcher.fetch(url, user_agent="kspo-ingest/0.2 CLI")
            await fetcher.close()

            html = result.raw_bytes.decode("utf-8", errors="replace")
            sel = AdaptiveSelector()
            matches = sel.select(html, css, adaptive=adaptive)

            typer.echo(f"URL: {result.url}")
            typer.echo(f"Selector: {css}")
            typer.echo(f"Matches: {len(matches)}")
            for i, m in enumerate(matches[:10]):
                text = m.node.text(strip=True)[:80] if m.node else ""
                typer.echo(
                    f"  [{i}] method={m.method} confidence={m.confidence:.2f} text=\"{text}\""
                )

        asyncio.run(_run())

    return app


def main() -> None:
    app = _create_app()
    app()


if __name__ == "__main__":
    main()
