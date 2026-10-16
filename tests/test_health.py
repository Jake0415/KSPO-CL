from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_healthz_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_request_id_header_generated(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    headers_lower = {k.lower() for k in r.headers}
    assert "x-request-id" in headers_lower
    assert len(r.headers["X-Request-Id"]) >= 16


@pytest.mark.asyncio
async def test_request_id_header_preserved(client):
    given = "abcdef0123456789"
    r = await client.get("/healthz", headers={"X-Request-Id": given})
    assert r.headers["X-Request-Id"] == given


@pytest.mark.asyncio
async def test_readyz_returns_proxy_field(client):
    r = await client.get("/readyz")
    body = r.json()
    assert "proxy_configured" in body
    assert isinstance(body["proxy_configured"], bool)
    assert body.get("redis") == "stub"
    # qdrant_dim: 통합 모드 healthy → 3072, 미가용 → 0
    assert body.get("qdrant_dim") in (0, 3072)
    assert body.get("qdrant_mode") in ("self_hosted", "external")
    # db / qdrant ping는 CI 단위 테스트 환경에선 fail → 503 가능
    assert r.status_code in (200, 503)


@pytest.mark.asyncio
async def test_docs_endpoint(client):
    r = await client.get("/docs")
    assert r.status_code == 200
