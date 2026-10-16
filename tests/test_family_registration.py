from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from kspo_ingest.crawl.family_sitemap import extract_family_hosts

MOCK_HTML = """
<html><body>
<select>
  <option value="https://www.sports.re.kr">스포츠과학원</option>
  <option value="https://www.ksponco.or.kr">올림픽공원</option>
</select>
</body></html>
"""


def test_extract_from_mock_html():
    """Sanity check that extract_family_hosts works with our mock HTML."""
    hosts = extract_family_hosts(MOCK_HTML)
    assert "www.sports.re.kr" in hosts
    assert "www.ksponco.or.kr" in hosts
