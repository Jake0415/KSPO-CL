"""Tests for crawl.session_mgr — Session management."""
from __future__ import annotations

import pytest

from kspo_ingest.crawl.session_mgr import SessionEntry, SessionManager


class TestSessionEntry:
    def test_not_expired_initially(self):
        entry = SessionEntry(host="example.com", client=None)  # type: ignore[arg-type]
        assert not entry.is_expired

    def test_expires_after_max_requests(self):
        entry = SessionEntry(host="example.com", client=None, max_requests=3)  # type: ignore[arg-type]
        entry.touch()
        entry.touch()
        entry.touch()
        assert entry.is_expired

    def test_touch_increments(self):
        entry = SessionEntry(host="example.com", client=None)  # type: ignore[arg-type]
        entry.touch()
        assert entry.request_count == 1
        entry.touch()
        assert entry.request_count == 2


class TestSessionManager:
    @pytest.fixture
    def mgr(self):
        return SessionManager()

    @pytest.mark.asyncio
    async def test_get_client_creates(self, mgr: SessionManager):
        client = await mgr.get_client("example.com", user_agent="TestAgent")
        assert client is not None
        assert mgr.active_sessions == 1
        await mgr.close_all()

    @pytest.mark.asyncio
    async def test_get_client_reuses(self, mgr: SessionManager):
        c1 = await mgr.get_client("example.com")
        c2 = await mgr.get_client("example.com")
        assert c1 is c2
        assert mgr.active_sessions == 1
        await mgr.close_all()

    @pytest.mark.asyncio
    async def test_different_hosts(self, mgr: SessionManager):
        await mgr.get_client("host1.com")
        await mgr.get_client("host2.com")
        assert mgr.active_sessions == 2
        await mgr.close_all()

    @pytest.mark.asyncio
    async def test_close_host(self, mgr: SessionManager):
        await mgr.get_client("host1.com")
        await mgr.get_client("host2.com")
        await mgr.close_host("host1.com")
        assert mgr.active_sessions == 1
        await mgr.close_all()

    @pytest.mark.asyncio
    async def test_close_all(self, mgr: SessionManager):
        await mgr.get_client("host1.com")
        await mgr.get_client("host2.com")
        await mgr.close_all()
        assert mgr.active_sessions == 0

    @pytest.mark.asyncio
    async def test_get_stats(self, mgr: SessionManager):
        await mgr.get_client("example.com")
        stats = mgr.get_stats()
        assert len(stats) == 1
        assert stats[0]["host"] == "example.com"
        assert stats[0]["requests"] == 0
        await mgr.close_all()
