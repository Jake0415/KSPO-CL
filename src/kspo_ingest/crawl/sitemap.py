"""Sitemap 자동 탐색 — robots.txt + 기본 경로에서 sitemap 발견 및 URL 추출."""
from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET

import httpx

from kspo_ingest.observability.logger import get_logger

log = get_logger("crawl", "sitemap")

_TIMEOUT = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=5.0)
_UA = "kspo-ingest/0.2"

# 기본 sitemap 경로
_DEFAULT_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap/sitemap.xml",
]

_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


@dataclass
class SitemapEntry:
    url: str
    lastmod: str | None = None
    changefreq: str | None = None
    priority: float | None = None


async def discover_sitemap_urls(host: str) -> list[str]:
    """도메인의 sitemap URL을 탐색. robots.txt + 기본 경로."""
    urls: list[str] = []

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _UA},
    ) as client:
        # 1. robots.txt에서 Sitemap: 추출
        try:
            resp = await client.get(f"https://{host}/robots.txt")
            if resp.status_code == 200:
                for line in resp.text.splitlines():
                    if line.strip().lower().startswith("sitemap:"):
                        sm_url = line.split(":", 1)[1].strip()
                        if sm_url and sm_url not in urls:
                            urls.append(sm_url)
        except Exception:
            pass

        # 2. 기본 경로 시도
        for path in _DEFAULT_PATHS:
            sm_url = f"https://{host}{path}"
            if sm_url in urls:
                continue
            try:
                resp = await client.head(sm_url)
                if resp.status_code == 200:
                    ct = resp.headers.get("content-type", "")
                    if "xml" in ct or "text" in ct:
                        urls.append(sm_url)
            except Exception:
                pass

    return urls


async def parse_sitemap(url: str) -> list[SitemapEntry]:
    """Sitemap XML 파싱. sitemap index면 재귀 파싱."""
    entries: list[SitemapEntry] = []

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return entries

        root = ET.fromstring(resp.content)
        tag = root.tag.lower()

        # Sitemap index → 재귀
        if "sitemapindex" in tag:
            for sitemap in root.findall("sm:sitemap", _NS):
                loc = sitemap.findtext("sm:loc", namespaces=_NS)
                if loc:
                    sub_entries = await parse_sitemap(loc)
                    entries.extend(sub_entries)
            # namespace 없는 경우도 처리
            for sitemap in root.findall("sitemap"):
                loc_el = sitemap.find("loc")
                if loc_el is not None and loc_el.text:
                    sub_entries = await parse_sitemap(loc_el.text.strip())
                    entries.extend(sub_entries)

        # URL set
        elif "urlset" in tag:
            for url_el in root.findall("sm:url", _NS):
                loc = url_el.findtext("sm:loc", namespaces=_NS)
                if loc:
                    entries.append(SitemapEntry(
                        url=loc.strip(),
                        lastmod=url_el.findtext("sm:lastmod", namespaces=_NS),
                        changefreq=url_el.findtext("sm:changefreq", namespaces=_NS),
                        priority=_parse_priority(url_el.findtext("sm:priority", namespaces=_NS)),
                    ))
            # namespace 없는 경우
            for url_el in root.findall("url"):
                loc_el = url_el.find("loc")
                if loc_el is not None and loc_el.text:
                    entries.append(SitemapEntry(
                        url=loc_el.text.strip(),
                        lastmod=(url_el.findtext("lastmod") or "").strip() or None,
                    ))

        log.bind(event="sitemap_parsed", url=url, entries=len(entries)).info("parsed")

    except ET.ParseError:
        log.bind(event="sitemap_parse_error", url=url).warning("XML parse error")
    except Exception as e:
        log.bind(event="sitemap_error", url=url, error=str(e)[:100]).warning("sitemap error")

    return entries


def _parse_priority(val: str | None) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except ValueError:
        return None
