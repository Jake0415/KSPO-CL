"""Tests for crawl.sitemap — Sitemap discovery and parsing."""
from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement, tostring

import pytest

from kspo_ingest.crawl.sitemap import SitemapEntry, _parse_priority


class TestParsePriority:
    def test_valid(self):
        assert _parse_priority("0.8") == 0.8

    def test_none(self):
        assert _parse_priority(None) is None

    def test_invalid(self):
        assert _parse_priority("abc") is None


class TestSitemapEntry:
    def test_defaults(self):
        e = SitemapEntry(url="https://example.com/page")
        assert e.url == "https://example.com/page"
        assert e.lastmod is None
        assert e.priority is None
