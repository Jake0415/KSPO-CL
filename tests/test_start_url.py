from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from kspo_ingest.crawl.start_url import (
    browser_required,
    entry_urls,
    parse_start_url,
    preflight_start,
)


def domain(**kw):
    return SimpleNamespace(
        **dict(
            host="example.com",
            scheme="https",
            start_url=None,
            use_playwright=False,
            user_agent=None,
            rate_limit_rps=1.5,
            **kw,
        )
    )


def test_entry_priority_and_query():
    d = domain()
    assert entry_urls(d) == ["https://example.com/"]
    d.start_url = "https://example.com/home"
    assert entry_urls(d) == [d.start_url]
    assert entry_urls(d, SimpleNamespace(seed_urls=["https://example.com/a?q=1#top"])) == [
        "https://example.com/a?q=1"
    ]
    assert parse_start_url("example.com/main.kspo") == "https://example.com/main.kspo"


@pytest.mark.parametrize(
    "url", ["ftp://example.com/a", "https://user:pass@example.com/", "https://example.com:99/"]
)
def test_invalid(url):
    with pytest.raises(ValueError):
        parse_start_url(url)


def test_scope_and_nfa():
    with pytest.raises(ValueError):
        entry_urls(domain(), SimpleNamespace(seed_urls=["https://other.com/"]))
    d = domain()
    d.host = "nfa.kspo.or.kr"
    assert entry_urls(d) == ["https://nfa.kspo.or.kr/"]
    assert browser_required(d)
    assert not browser_required(domain())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,url,html,ok",
    [
        (
            200,
            "https://example.com/home",
            b'<main>Public site navigation</main><a href="/a">Details</a>',
            True,
        ),
        (503, "https://example.com/", b"error", False),
        (200, "https://other.com/", b"outside", False),
        (200, "https://example.com/login", b"login", False),
        (200, "https://example.com/", b"<html></html>", False),
    ],
)
async def test_preflight(status, url, html, ok):
    smart = SimpleNamespace(
        fetch=AsyncMock(return_value=SimpleNamespace(http_status=status, url=url, raw_bytes=html))
    )
    ctx = {"smart_fetcher": smart, "rate_limit": SimpleNamespace(acquire=AsyncMock())}
    with patch("kspo_ingest.crawl.external_fetch.validate_destination", new=AsyncMock()):
        if ok:
            await preflight_start(ctx, domain(), ["https://example.com/"])
        else:
            with pytest.raises(RuntimeError):
                await preflight_start(ctx, domain(), ["https://example.com/"])


@pytest.mark.asyncio
async def test_failed_preflight_never_resets_existing_site():
    from unittest.mock import MagicMock

    from kspo_ingest.db.models import Domain
    from kspo_ingest.tasks.pipeline.enqueue_seeds import _enqueue_seeds_impl

    d = domain()
    d.max_pages = 2000
    d.max_depth = 10
    session = AsyncMock()
    session.get.side_effect = lambda model, key: (
        d if model is Domain else SimpleNamespace(seed_urls=None)
    )
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    sonar = SimpleNamespace(reset_site=AsyncMock())
    ctx = {"session_factory": factory, "frontier": AsyncMock(), "sonar_client": sonar}
    with (
        patch("kspo_ingest.tasks.pipeline.enqueue_seeds.start_job", new=AsyncMock()),
        patch(
            "kspo_ingest.crawl.start_url.preflight_start",
            new=AsyncMock(side_effect=RuntimeError("offline")),
        ),
        pytest.raises(RuntimeError, match="offline"),
    ):
        await _enqueue_seeds_impl(ctx, job_id=1, domain_id=1)
    sonar.reset_site.assert_not_awaited()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_fallback_fetcher_and_browser_unavailable():
    fetcher = SimpleNamespace(
        fetch=AsyncMock(
            return_value=SimpleNamespace(
                http_status=200,
                url="https://example.com/",
                raw_bytes=b'<a href="/a">Useful public navigation</a>',
            )
        )
    )
    ctx = {"fetcher": fetcher, "rate_limit": SimpleNamespace(acquire=AsyncMock())}
    with patch("kspo_ingest.crawl.external_fetch.validate_destination", new=AsyncMock()):
        await preflight_start(ctx, domain(), ["https://example.com/"])
        d = domain()
        d.use_playwright = True
        with pytest.raises(RuntimeError, match="Browser fetcher"):
            await preflight_start(ctx, d, ["https://example.com/"])


def test_migration_only_adds_nullable_column():
    import ast
    from pathlib import Path
    from unittest.mock import MagicMock

    import sqlalchemy as sa

    source = Path(__file__).parents[1] / "migrations/versions/0009_domain_start_url.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    upgrade = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
    op = MagicMock()
    scope = {"op": op, "sa": sa}
    exec(compile(ast.Module(body=[upgrade], type_ignores=[]), str(source), "exec"), scope)
    scope["upgrade"]()
    args = op.add_column.call_args.args
    assert args[0] == "domains"
    assert args[1].name == "start_url" and args[1].nullable
    assert len(op.mock_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,final_url,reason",
    [
        (404, "https://example.com/missing", "HTTP error"),
        (200, "chrome-error://chromewebdata/", "outside domain"),
    ],
)
async def test_preflight_error_contains_actual_status_and_destination(status, final_url, reason):
    ctx = {
        "smart_fetcher": SimpleNamespace(
            fetch=AsyncMock(
                return_value=SimpleNamespace(http_status=status, url=final_url, raw_bytes=b"")
            )
        ),
        "rate_limit": SimpleNamespace(acquire=AsyncMock()),
    }
    with (
        patch("kspo_ingest.crawl.external_fetch.validate_destination", new=AsyncMock()),
        pytest.raises(RuntimeError, match=reason) as exc,
    ):
        await preflight_start(ctx, domain(), ["https://example.com/"])
    assert f"status={status}" in str(exc.value)
    assert f"final_url={final_url}" in str(exc.value)


@pytest.mark.asyncio
async def test_preflight_invalidates_failure_once_per_job_and_keeps_input_urls():
    from unittest.mock import Mock

    urls = ["https://example.com/sub/main.kspo?q=1", "https://example.com/other"]
    smart = SimpleNamespace(
        reset_failed_profile=Mock(),
        fetch=AsyncMock(
            return_value=SimpleNamespace(
                http_status=200, url=urls[0], raw_bytes=b'<a href="/a">Useful public navigation</a>'
            )
        ),
    )
    ctx = {"smart_fetcher": smart, "rate_limit": SimpleNamespace(acquire=AsyncMock())}
    with patch("kspo_ingest.crawl.external_fetch.validate_destination", new=AsyncMock()):
        await preflight_start(ctx, domain(), urls)
    smart.reset_failed_profile.assert_called_once_with("example.com")
    assert [call.args[0] for call in smart.fetch.await_args_list] == urls
    assert all(not call.kwargs["force_browser"] for call in smart.fetch.await_args_list)
