from unittest.mock import AsyncMock

import httpx
import pytest

from kspo_ingest.sonar.client import SonarClient


@pytest.mark.asyncio
async def test_reset_only_deletes_matching_host():
    deleted = []

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "count": 3,
                    "kbs": [
                        {"_id": "a", "source": "https://soma.kspo.or.kr/main"},
                        {"_id": "b", "source": "https://svoucher.kspo.or.kr/main.do"},
                        {"_id": "c", "source": "https://soma.kspo.or.kr.evil.test/"},
                    ],
                },
            )
        deleted.append(request.url.path)
        return httpx.Response(200, json={})

    client = SonarClient(base_url="https://sonar.test", email="", password="", project_id="p")
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    client._get_token = AsyncMock(return_value="test")
    try:
        assert await client.reset_site(host="soma.kspo.or.kr", namespace="n") == 1
        assert deleted == ["/api/p/kb/a"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_reset_delete_failure_propagates():
    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"count": 1, "kbs": [{"_id": "a", "source": "https://soma.kspo.or.kr/main"}]},
            )
        return httpx.Response(500)

    client = SonarClient(base_url="https://sonar.test", email="", password="", project_id="p")
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    client._get_token = AsyncMock(return_value="test")
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.reset_site(host="soma.kspo.or.kr", namespace="n")
    finally:
        await client.close()
