from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from kspo_ingest.api.deps import db_session
from kspo_ingest.api.main import create_app
from kspo_ingest.db.models import Attachment


@pytest.fixture
def app_with_session():
    """db_session dependency를 AsyncMock으로 override — PG 없이 endpoint 검증."""
    app = create_app()
    fake_session = AsyncMock()

    async def _override():
        yield fake_session

    app.dependency_overrides[db_session] = _override
    return app, fake_session


@pytest.fixture
async def files_client(app_with_session):
    app, _ = app_with_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_existing_attachment_redirects_to_source_url(app_with_session, files_client):
    _, session = app_with_session
    source = "https://www.kspo.or.kr/board/download?id=42"
    att = Attachment(
        id=42,
        page_id=1,
        domain_id=1,
        source_url=source,
        file_name="공고.pdf",
        file_hash="a" * 64,
        storage_path="",
        extraction_status="SKIPPED",
    )
    session.get.return_value = att

    r = await files_client.get("/files/42", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == source


async def test_missing_attachment_returns_404(app_with_session, files_client):
    _, session = app_with_session
    session.get.return_value = None

    r = await files_client.get("/files/9999", follow_redirects=False)
    assert r.status_code == 404
    assert r.json()["detail"] == "attachment not found"


async def test_attachment_without_source_url_returns_404(app_with_session, files_client):
    _, session = app_with_session
    att = Attachment(
        id=10,
        page_id=1,
        domain_id=1,
        source_url="",
        file_hash="b" * 64,
        storage_path="",
        extraction_status="SKIPPED",
    )
    session.get.return_value = att

    r = await files_client.get("/files/10", follow_redirects=False)
    assert r.status_code == 404


async def test_endpoint_does_not_require_authentication(app_with_session, files_client):
    """챗봇 화이트리스트 — Basic/세션 인증 헤더 없이도 정상 응답해야 함."""
    _, session = app_with_session
    att = Attachment(
        id=1,
        page_id=1,
        domain_id=1,
        source_url="https://example.com/x.pdf",
        file_hash="c" * 64,
        storage_path="",
        extraction_status="SKIPPED",
    )
    session.get.return_value = att

    # 인증 헤더 없이 호출 → 401 아닌 302 redirect
    r = await files_client.get("/files/1", follow_redirects=False)
    assert r.status_code == 302
    assert "www-authenticate" not in {k.lower() for k in r.headers}
