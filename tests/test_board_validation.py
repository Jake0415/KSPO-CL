from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kspo_ingest.crawl.board_validation import entry_url, validate_board

GOOD = """<main><table><thead><tr><th>제목</th><th>게시일</th></tr></thead>
<tr><td><a href="/board/view.do?nttId=1">글 하나</a></td><td>2026.10.12</td></tr>
<tr><td><a href="/board/view.do?nttId=2">글 둘</a></td><td>2026.10.13</td></tr>
</table></main>"""
URL = "https://x.kr/board/list.do?bbsId=A"


def test_first_entry_preserves_board_identity_only():
    assert entry_url(URL + "&pageIndex=7&searchWrd=abc&utm_source=x", "x.kr") == URL
    assert entry_url("https://x.kr/news/page/3", "x.kr") == "https://x.kr/news"
    assert entry_url("https://x.kr/board/view.do?bbsId=A&nttId=1", "x.kr") == URL
    assert entry_url("https://x.kr/boardList.do?boardSeq=7", "x.kr")
    assert entry_url("https://x.kr/boardView.do?boardSeq=7&conSeq=1", "x.kr") == (
        "https://x.kr/boardList.do?boardSeq=7"
    )
    assert entry_url("https://other.kr/board/list.do", "x.kr") is None
    assert entry_url("https://x.kr/product/221", "x.kr") is None


def test_requires_unique_dated_body_list():
    assert validate_board(GOOD, URL, "x.kr").valid
    assert not validate_board(GOOD.replace("nttId=2", "nttId=1"), URL, "x.kr").valid
    assert not validate_board(GOOD, "https://x.kr/board/view.do?nttId=1", "x.kr").valid
    assert not validate_board(GOOD.replace("게시일", "전시기간"), URL, "x.kr").valid
    assert not validate_board(
        GOOD.replace("2026.10.12", "").replace("2026.10.13", ""), URL, "x.kr"
    ).valid


@pytest.mark.parametrize("tag", ["header", "footer", "nav", "aside"])
def test_navigation_is_not_board(tag):
    assert not validate_board(f"<{tag}>{GOOD}</{tag}>", URL, "x.kr").valid


def test_related_and_dynamic_blocks_are_not_boards():
    assert not validate_board(f'<div class="related">{GOOD}</div>', URL, "x.kr").valid
    assert not validate_board(
        f'<section data-rag-dynamic="true">{GOOD}</section>', URL, "x.kr"
    ).valid
    assert not validate_board(
        GOOD, "https://soma.kspo.or.kr/piece/product/221", "soma.kspo.or.kr"
    ).valid


@pytest.mark.asyncio
async def test_later_page_html_cannot_approve_first_entry():
    from kspo_ingest.crawl.board_detect import verify_entry

    domain = SimpleNamespace(host="x.kr", user_agent=None)
    empty = SimpleNamespace(
        http_status=200, url=URL, raw_bytes=b"<main>not a board</main>", content_type="text/html"
    )
    fetcher = SimpleNamespace(fetch=AsyncMock(return_value=empty))
    verdict = await verify_entry(
        URL + "&pageIndex=8", domain, html=GOOD, fetched_url=URL + "&pageIndex=8", fetcher=fetcher
    )
    assert not verdict.valid
    assert fetcher.fetch.call_args.args[0] == URL


@pytest.mark.asyncio
async def test_legacy_invalid_and_duplicate_keep_record():
    from kspo_ingest.crawl.board_detect import revalidate_source

    domain = SimpleNamespace(host="x.kr", user_agent=None)

    class Session:
        async def execute(self, statement):
            return SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(id=2))

        async def commit(self):
            pass

    source = SimpleNamespace(
        id=1, domain_id=1, list_url="https://other.kr/list", status="confirmed"
    )
    assert await revalidate_source(Session(), source, domain) is None
    assert source.status == "invalid"
    assert source.validation_error == "not_list_url_or_wrong_host"
    source.list_url = URL
    fetcher = SimpleNamespace(
        fetch=AsyncMock(
            return_value=SimpleNamespace(
                http_status=200,
                url=URL,
                raw_bytes=GOOD.encode(),
                content_type="text/html;charset=utf-8",
            )
        )
    )
    assert await revalidate_source(Session(), source, domain, fetcher=fetcher) is None
    assert source.validation_error == "duplicate_first_entry"


@pytest.mark.parametrize(
    "path",
    ["/", "/main/main.kspo", "/news/main/main.do", "/index.html", "/portal/home", "/default.aspx"],
)
def test_landing_preview_is_never_registered_as_board(path):
    url = "https://x.kr" + path
    assert entry_url(url, "x.kr") is None
    verdict = validate_board(GOOD, url, "x.kr")
    assert not verdict.valid
    assert verdict.reason == "landing_page_not_board"


@pytest.mark.parametrize(
    "path",
    [
        "/?boardId=A",
        "/index.php?module=board",
        "/index.php?route=board/list",
        "/board/list.do?bbsId=A",
    ],
)
def test_query_routed_boards_and_real_list_remain_supported(path):
    url = "https://x.kr" + path
    assert entry_url(url, "x.kr") is not None
    assert validate_board(GOOD, url, "x.kr").valid


@pytest.mark.asyncio
async def test_legacy_landing_board_invalidates_without_refetch():
    from kspo_ingest.crawl.board_detect import revalidate_source

    source = SimpleNamespace(
        id=1, domain_id=1, list_url="https://x.kr/main/main.kspo", status="confirmed"
    )
    session = SimpleNamespace(commit=AsyncMock())
    fetcher = SimpleNamespace(fetch=AsyncMock())
    result = await revalidate_source(
        session, source, SimpleNamespace(host="x.kr", user_agent=None), fetcher=fetcher
    )
    assert result is None
    assert source.status == "invalid"
    fetcher.fetch.assert_not_awaited()
    session.commit.assert_awaited_once()
