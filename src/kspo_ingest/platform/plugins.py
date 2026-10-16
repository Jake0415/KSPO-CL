"""Plugin system — 확장 포인트 등록/로드.

설계 원칙:
- 플러그인은 단순 Python 모듈 (install_plugin 호출)
- Hook 기반: 파이프라인 각 단계에 전/후 처리 주입
- Tool 확장: Agent에 커스텀 도구 추가
- Fetcher 확장: 커스텀 페처 등록
"""
from __future__ import annotations

import importlib
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from kspo_ingest.observability.logger import get_logger

log = get_logger("platform", "plugins")


@dataclass
class PluginMeta:
    """플러그인 메타데이터."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""


HookFn = Callable[..., Coroutine[Any, Any, Any]]

# Hook 이름 → 핸들러 목록
HookName = str  # e.g., "before_fetch", "after_clean", "on_error"


class PluginManager:
    """플러그인 관리자.

    사용법:
        pm = PluginManager()

        # 플러그인 등록
        @pm.hook("before_fetch")
        async def log_fetch(url: str, **kwargs):
            print(f"Fetching: {url}")

        # 후크 실행
        await pm.run_hook("before_fetch", url="https://example.com")

        # 모듈에서 로드
        pm.load_module("my_plugin.module")
    """

    def __init__(self) -> None:
        self._plugins: dict[str, PluginMeta] = {}
        self._hooks: dict[HookName, list[HookFn]] = {}

    def register(self, meta: PluginMeta) -> None:
        self._plugins[meta.name] = meta
        log.bind(event="plugin_registered", plugin=meta.name).info("plugin registered")

    def hook(self, name: HookName) -> Callable[[HookFn], HookFn]:
        """데코레이터 — hook에 핸들러 등록."""

        def decorator(fn: HookFn) -> HookFn:
            self._hooks.setdefault(name, []).append(fn)
            return fn

        return decorator

    def add_hook(self, name: HookName, fn: HookFn) -> None:
        """직접 hook 핸들러 추가."""
        self._hooks.setdefault(name, []).append(fn)

    async def run_hook(self, name: HookName, **kwargs: Any) -> list[Any]:
        """Hook 실행 — 등록된 모든 핸들러를 순서대로 실행."""
        handlers = self._hooks.get(name, [])
        results: list[Any] = []
        for fn in handlers:
            try:
                result = await fn(**kwargs)
                results.append(result)
            except Exception as e:
                log.bind(
                    event="hook_error", hook=name, error=str(e),
                ).warning("hook error")
        return results

    def load_module(self, module_path: str) -> None:
        """Python 모듈을 로드하여 install_plugin() 호출."""
        try:
            mod = importlib.import_module(module_path)
            if hasattr(mod, "install_plugin"):
                mod.install_plugin(self)
                log.bind(event="plugin_loaded", module=module_path).info("plugin loaded")
            else:
                log.bind(
                    event="plugin_no_installer", module=module_path,
                ).warning("no install_plugin function")
        except ImportError as e:
            log.bind(
                event="plugin_import_error", module=module_path, error=str(e),
            ).warning("plugin import failed")

    @property
    def plugin_names(self) -> list[str]:
        return list(self._plugins.keys())

    @property
    def hook_names(self) -> list[HookName]:
        return list(self._hooks.keys())

    def get_hook_count(self, name: HookName) -> int:
        return len(self._hooks.get(name, []))


# Available hook points
HOOK_POINTS = [
    "before_fetch",
    "after_fetch",
    "before_clean",
    "after_clean",
    "before_refine",
    "after_refine",
    "before_chunk",
    "after_chunk",
    "before_index",
    "after_index",
    "on_error",
    "on_page_discovered",
    "on_page_dropped",
    "on_job_start",
    "on_job_finish",
]

# 글로벌 플러그인 매니저
plugin_manager = PluginManager()
