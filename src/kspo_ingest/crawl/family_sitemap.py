from __future__ import annotations

from urllib.parse import urlparse

from selectolax.parser import HTMLParser

FAMILY_ALLOWLIST: frozenset[str] = frozenset({
    "kspo.or.kr",
    "sports.re.kr",
    "ksponco.or.kr",
    "kcycle.or.kr",
    "kboat.or.kr",
    "spoex.com",
    "spoinfo.or.kr",
    "parktel.co.kr",
    "ecolian.or.kr",
})

# DNS 실패 또는 폐쇄 확인된 도메인 (2026-07-05 probe 결과)
# - spoex.or.kr: DNS 실패 (spoex.com으로 통합)
# - sportsindustry.or.kr: DNS 실패
# - nest.kspo.or.kr: 타임아웃 (내부망 전용 추정)
# - asset.kspo.or.kr: DNS 실패 (내부망 전용 추정)


def _is_allowed(host: str) -> bool:
    host_lower = host.lower()
    return any(host_lower == a or host_lower.endswith("." + a) for a in FAMILY_ALLOWLIST)


def extract_family_hosts(html: str) -> list[str]:
    if not html:
        return []
    tree = HTMLParser(html)
    urls: set[str] = set()
    for option in tree.css("option[value]"):
        val = (option.attributes.get("value") or "").strip()
        if val and val.startswith("http"):
            urls.add(val)
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if href and href.startswith("http"):
            urls.add(href)
    hosts: list[str] = []
    seen: set[str] = set()
    for url in sorted(urls):
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host and host not in seen and _is_allowed(host):
            seen.add(host)
            hosts.append(host)
    return hosts
