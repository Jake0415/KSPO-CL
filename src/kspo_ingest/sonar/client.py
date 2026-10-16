"""SONAR (tiledesk-llm) 클라이언트 — 로그인·토큰 캐시·KB POST + 재시도.

사용:
    client = SonarClient(base_url=..., email=..., password=..., project_id=...)
    result = await client.upsert_kb(
        name="...", content="...", source="...",
        namespace="...", tags=["kspo", ...],
    )

인증 헤더: `Authorization: <token>` (prefix 없음). Tiledesk 계열 SONAR는 signin으로
받은 토큰을 원시값 그대로 요구한다. Bearer/JWT 스킴은 401 반환.
"""

from __future__ import annotations

import asyncio

import httpx


class SonarError(Exception):
    """SONAR API 호출 실패 (재시도 소진 후)."""


class SonarClient:
    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        password: str,
        project_id: str,
        timeout_seconds: float = 60.0,
        retry_max: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._project_id = project_id
        self._timeout = timeout_seconds
        self._retry_max = retry_max
        self._backoff = retry_backoff_seconds
        self._token: str | None = None
        self._token_lock = asyncio.Lock()
        self._client = httpx.AsyncClient(timeout=self._timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def _login(self) -> str:
        r = await self._client.post(
            f"{self._base}/api/auth/signin",
            json={"email": self._email, "password": self._password},
            timeout=10.0,
        )
        r.raise_for_status()
        token = r.json().get("token")
        if not token:
            raise SonarError("signin 응답에 token 없음")
        return token

    async def _get_token(self, *, force_refresh: bool = False) -> str:
        async with self._token_lock:
            if force_refresh:
                self._token = None
            if self._token is None:
                self._token = await self._login()
            return self._token

    async def upsert_kb(
        self,
        *,
        name: str,
        content: str,
        source: str,
        namespace: str,
        tags: list[str],
    ) -> dict:
        """단일 KB 문서 등록. 실패 시 재시도(5xx만) 후 SonarError 전파."""
        payload = {
            "name": name[:200],
            "type": "text",
            "content": content,
            "source": source,
            "namespace": namespace,
            "tags": tags,
        }
        url = f"{self._base}/api/{self._project_id}/kb"

        last_exc: Exception | None = None
        for attempt in range(self._retry_max):
            try:
                token = await self._get_token()
                r = await self._client.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": token,
                    },
                )
                if r.status_code == 401:
                    # 토큰 만료 — 갱신 후 즉시 재시도 (attempt 소진 안 함)
                    await self._get_token(force_refresh=True)
                    r = await self._client.post(
                        url,
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": self._token or "",
                        },
                    )
                if 500 <= r.status_code < 600:
                    # 5xx만 재시도
                    last_exc = SonarError(f"HTTP {r.status_code}: {r.text[:200]}")
                    await asyncio.sleep(self._backoff * (2**attempt))
                    continue
                r.raise_for_status()
                return r.json()
            except httpx.TransportError as exc:
                last_exc = exc
                await asyncio.sleep(self._backoff * (2**attempt))
                continue
            except httpx.HTTPStatusError as exc:
                # 4xx (401/403 갱신 실패 포함) — 즉시 전파, 재시도 무의미
                raise SonarError(
                    f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
                ) from exc

        raise SonarError(f"재시도 {self._retry_max}회 소진: {last_exc}")

    async def trigger_scrape_single(
        self, *, kb_id: str, namespace: str, kb_type: str = "text"
    ) -> dict:
        """upsert_kb로 생성된 KB 문서를 인덱싱 큐에 트리거.

        Tiledesk-server의 POST /kb/scrape/single 호출 — namespace.hybrid에 따라
        RabbitMQ 큐 publish 또는 aiService.singleScrape의 HTTP path로 흐른다.
        이 호출을 하지 않으면 KB 문서는 mongo에 status:-1 상태로 방치돼 검색 불가.
        """
        payload = {"id": kb_id, "namespace": namespace, "type": kb_type}
        url = f"{self._base}/api/{self._project_id}/kb/scrape/single"

        last_exc: Exception | None = None
        for attempt in range(self._retry_max):
            try:
                token = await self._get_token()
                r = await self._client.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": token,
                    },
                )
                if r.status_code == 401:
                    await self._get_token(force_refresh=True)
                    r = await self._client.post(
                        url,
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": self._token or "",
                        },
                    )
                if 500 <= r.status_code < 600:
                    last_exc = SonarError(f"HTTP {r.status_code}: {r.text[:200]}")
                    await asyncio.sleep(self._backoff * (2**attempt))
                    continue
                r.raise_for_status()
                return r.json() if r.text else {}
            except httpx.TransportError as exc:
                last_exc = exc
                await asyncio.sleep(self._backoff * (2**attempt))
                continue
            except httpx.HTTPStatusError as exc:
                raise SonarError(
                    f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
                ) from exc

        raise SonarError(f"scrape/single 재시도 {self._retry_max}회 소진: {last_exc}")

    async def reset_site(self, *, host: str, namespace: str) -> int:
        """Remove only this site's documents, without deleting other sites.

        Snapshot IDs before deletion so pagination cannot skip shifting rows.
        Fail closed: a failed delete must prevent the subsequent rebuild.
        """
        from urllib.parse import urlsplit

        ids: set[str] = set()
        page = 0
        while True:
            token = await self._get_token()
            response = await self._client.get(
                f"{self._base}/api/{self._project_id}/kb",
                params={"namespace": namespace, "limit": 200, "page": page},
                headers={"Authorization": token},
            )
            if response.status_code == 401:
                token = await self._get_token(force_refresh=True)
                response = await self._client.get(
                    f"{self._base}/api/{self._project_id}/kb",
                    params={"namespace": namespace, "limit": 200, "page": page},
                    headers={"Authorization": token},
                )
            response.raise_for_status()
            data = response.json()
            documents = data["kbs"]
            for document in documents:
                source = document.get("source") or ""
                if urlsplit(source).hostname == host:
                    ids.add(str(document["_id"]))
            if (page + 1) * 200 >= data["count"]:
                break
            page += 1
        for ident in sorted(ids):
            token = await self._get_token()
            response = await self._client.delete(
                f"{self._base}/api/{self._project_id}/kb/{ident}",
                headers={"Authorization": token},
            )
            if response.status_code == 401:
                token = await self._get_token(force_refresh=True)
                response = await self._client.delete(
                    f"{self._base}/api/{self._project_id}/kb/{ident}",
                    headers={"Authorization": token},
                )
            if response.status_code != 404:
                response.raise_for_status()
        return len(ids)
