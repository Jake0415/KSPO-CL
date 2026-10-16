"""Tests for platform.plugins — Plugin system."""
from __future__ import annotations

import pytest

from kspo_ingest.platform.plugins import HOOK_POINTS, PluginManager, PluginMeta


class TestPluginManager:
    @pytest.fixture
    def pm(self):
        return PluginManager()

    def test_register_plugin(self, pm):
        meta = PluginMeta(name="test-plugin", version="1.0.0")
        pm.register(meta)
        assert "test-plugin" in pm.plugin_names

    def test_hook_decorator(self, pm):
        @pm.hook("before_fetch")
        async def my_hook(url: str):
            return f"fetching {url}"

        assert pm.get_hook_count("before_fetch") == 1

    def test_add_hook(self, pm):
        async def handler():
            pass

        pm.add_hook("after_clean", handler)
        assert pm.get_hook_count("after_clean") == 1

    @pytest.mark.asyncio
    async def test_run_hook(self, pm):
        results = []

        @pm.hook("on_error")
        async def handler1(error: str):
            results.append(f"h1: {error}")
            return "handled1"

        @pm.hook("on_error")
        async def handler2(error: str):
            results.append(f"h2: {error}")
            return "handled2"

        returned = await pm.run_hook("on_error", error="test_error")
        assert len(results) == 2
        assert results[0] == "h1: test_error"
        assert returned == ["handled1", "handled2"]

    @pytest.mark.asyncio
    async def test_run_hook_empty(self, pm):
        results = await pm.run_hook("nonexistent_hook")
        assert results == []

    @pytest.mark.asyncio
    async def test_run_hook_error_handling(self, pm):
        @pm.hook("test_hook")
        async def failing_hook():
            raise ValueError("boom")

        @pm.hook("test_hook")
        async def ok_hook():
            return "ok"

        results = await pm.run_hook("test_hook")
        # 첫 번째 에러가 나도 두 번째는 실행
        assert len(results) == 1
        assert results[0] == "ok"

    def test_hook_names(self, pm):
        pm.add_hook("a", lambda: None)
        pm.add_hook("b", lambda: None)
        assert set(pm.hook_names) == {"a", "b"}

    def test_load_module_missing(self, pm):
        # 존재하지 않는 모듈 — 에러만 로그
        pm.load_module("nonexistent.module.path")
        assert len(pm.plugin_names) == 0


class TestHookPoints:
    def test_standard_hooks_defined(self):
        assert "before_fetch" in HOOK_POINTS
        assert "after_clean" in HOOK_POINTS
        assert "on_error" in HOOK_POINTS
        assert "on_job_start" in HOOK_POINTS
