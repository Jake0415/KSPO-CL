from __future__ import annotations

import pytest

from kspo_ingest.crawl.family_sitemap import FAMILY_ALLOWLIST, extract_family_hosts

SAMPLE_HTML = """
<html><body>
<select id="familySite" class="family-site">
  <option value="">패밀리 사이트</option>
  <option value="https://www.sports.re.kr">한국스포츠과학원</option>
  <option value="https://www.ksponco.or.kr">올림픽공원</option>
  <option value="https://spowell.kspo.or.kr">스포웰</option>
  <option value="https://evil.example.com">악의적 사이트</option>
</select>
<ul class="family-links">
  <li><a href="https://www.kcycle.or.kr">경륜</a></li>
  <li><a href="https://www.kboat.or.kr">경정</a></li>
</ul>
</body></html>
"""

def test_extract_family_hosts_from_select():
    hosts = extract_family_hosts(SAMPLE_HTML)
    assert "www.sports.re.kr" in hosts
    assert "www.ksponco.or.kr" in hosts
    assert "spowell.kspo.or.kr" in hosts

def test_extract_family_hosts_from_links():
    hosts = extract_family_hosts(SAMPLE_HTML)
    assert "www.kcycle.or.kr" in hosts
    assert "www.kboat.or.kr" in hosts

def test_allowlist_blocks_unknown_hosts():
    hosts = extract_family_hosts(SAMPLE_HTML)
    assert "evil.example.com" not in hosts

def test_extract_empty_html():
    hosts = extract_family_hosts("")
    assert hosts == []

def test_allowlist_is_not_empty():
    assert len(FAMILY_ALLOWLIST) >= 5
