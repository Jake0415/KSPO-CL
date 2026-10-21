from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kspo_ingest.clean.extractor import extract
from kspo_ingest.crawl.readiness import read_page_content


@pytest.mark.asyncio
async def test_navigation_race_recovers():
    page = SimpleNamespace(
        content=AsyncMock(
            side_effect=[
                RuntimeError("Page.content: page is navigating and changing the content"),
                "<main>튼튼머니 소개</main>",
            ]
        )
    )
    assert "튼튼머니" in await read_page_content(page)
    assert page.content.await_count == 2


@pytest.mark.asyncio
async def test_unrelated_error_is_not_retried():
    page = SimpleNamespace(content=AsyncMock(side_effect=RuntimeError("Target page closed")))
    with pytest.raises(RuntimeError, match="closed"):
        await read_page_content(page)
    assert page.content.await_count == 1


@pytest.mark.asyncio
async def test_navigation_retry_is_bounded():
    page = SimpleNamespace(content=AsyncMock(side_effect=RuntimeError("page is navigating")))
    with pytest.raises(TimeoutError):
        await read_page_content(page, timeout_ms=20)


def test_source_image_description_preserved_without_chrome():
    html = (
        '<html><body><nav><img alt="상단 메뉴 장식 이미지 안내"></nav>'
        '<main><h1>튼튼머니 소개</h1><img alt="체력진단과 스포츠활동에 참여하여 '
        '튼튼머니 포인트를 적립하고 스포츠용품 구매 등에 사용할 수 있습니다.">'
        "</main></body></html>"
    )
    result = extract(html.encode("utf-8"), "text/html; charset=utf-8")
    assert "스포츠활동에 참여하여 튼튼머니 포인트" in result.body_text
    assert "상단 메뉴 장식" not in result.body_text
    assert "data-rag-image-alt" not in result.body_text
