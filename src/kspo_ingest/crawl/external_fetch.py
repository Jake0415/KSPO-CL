"""Public HTTP-only external fetch: isolated cookies and validated redirect destinations."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from kspo_ingest.crawl.external_links import public_url


@dataclass
class ExternalResult:
    http_status: int
    content_type: str
    raw_bytes: bytes
    elapsed_ms: int = 0
    url: str = ""


async def validate_destination(url: str) -> None:
    if not public_url(url):
        raise ValueError("external destination is not a public HTTP URL")
    p = urlsplit(url)
    addresses = await asyncio.get_running_loop().getaddrinfo(
        p.hostname, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM
    )
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("external destination resolves to a non-public address")


async def fetch_external(url: str, *, user_agent: str) -> ExternalResult:
    import httpx

    async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
        for _ in range(6):
            await validate_destination(url)
            async with client.stream("GET", url, headers={"User-Agent": user_agent}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("external redirect has no destination")
                    url = urljoin(url, location)
                    continue
                content_type = response.headers.get("content-type", "")
                if response.status_code < 400 and not any(
                    value in content_type.lower() for value in ("text/html", "application/xhtml")
                ):
                    raise ValueError("external target is not an HTML page")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 2 * 1024 * 1024:
                        raise ValueError("external page exceeds 2 MiB")
                return ExternalResult(response.status_code, content_type, bytes(body), url=url)
    raise ValueError("external redirect limit exceeded")
