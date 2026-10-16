"""Plugin 예제 — 커스텀 hook 등록."""
import asyncio

from kspo_ingest.platform.plugins import PluginManager, PluginMeta


async def main():
    pm = PluginManager()

    # 플러그인 메타 등록
    pm.register(PluginMeta(
        name="example-logger",
        version="1.0.0",
        description="페치 전후 로깅 플러그인",
    ))

    # Hook 등록
    @pm.hook("before_fetch")
    async def log_before(url: str, **kwargs):
        print(f"  [before_fetch] {url}")
        return {"url": url}

    @pm.hook("after_fetch")
    async def log_after(url: str, status: int = 0, **kwargs):
        print(f"  [after_fetch] {url} → {status}")

    @pm.hook("on_error")
    async def log_error(error: str, **kwargs):
        print(f"  [on_error] {error}")

    # Hook 실행 시뮬레이션
    print("=== 페치 시뮬레이션 ===")
    url = "https://www.kspo.or.kr/"

    await pm.run_hook("before_fetch", url=url)
    print(f"  ... fetching {url}")
    await pm.run_hook("after_fetch", url=url, status=200)

    print(f"\n등록된 플러그인: {pm.plugin_names}")
    print(f"등록된 훅: {pm.hook_names}")


if __name__ == "__main__":
    asyncio.run(main())
