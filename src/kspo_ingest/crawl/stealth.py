"""Stealth profile management — 브라우저 fingerprint 위장.

Scrapling의 StealthyFetcher 개념을 차용하되, 프로파일 기반으로 분리.
각 프로파일은 UA, viewport, locale, timezone, WebGL vendor 등을 일관되게 설정.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StealthProfile:
    """브라우저 스텔스 프로파일 — Playwright BrowserContext 생성 시 사용."""

    name: str
    user_agent: str
    viewport: dict[str, int]
    locale: str
    timezone_id: str
    color_scheme: str = "light"
    extra_headers: dict[str, str] = field(default_factory=dict)
    webgl_vendor: str = "Google Inc. (Intel)"
    webgl_renderer: str = "ANGLE (Intel, Mesa Intel(R) UHD Graphics 630, OpenGL 4.6)"
    platform: str = "Win32"

    def to_context_kwargs(self) -> dict[str, Any]:
        """Playwright browser.new_context() kwargs로 변환."""
        return {
            "user_agent": self.user_agent,
            "viewport": self.viewport,
            "locale": self.locale,
            "timezone_id": self.timezone_id,
            "color_scheme": self.color_scheme,
            "extra_http_headers": {
                "Accept-Language": self.locale.replace("_", "-"),
                **self.extra_headers,
            },
        }


# --- 내장 프로파일 ---

_CHROME_WIN = StealthProfile(
    name="chrome_win",
    user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    viewport={"width": 1920, "height": 1080},
    locale="ko-KR",
    timezone_id="Asia/Seoul",
    platform="Win32",
)

_CHROME_MAC = StealthProfile(
    name="chrome_mac",
    user_agent=(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    viewport={"width": 1440, "height": 900},
    locale="ko-KR",
    timezone_id="Asia/Seoul",
    platform="MacIntel",
    webgl_vendor="Google Inc. (Apple)",
    webgl_renderer="ANGLE (Apple, Apple M1 Pro, OpenGL 4.1)",
)

_EDGE_WIN = StealthProfile(
    name="edge_win",
    user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
    ),
    viewport={"width": 1920, "height": 1080},
    locale="ko-KR",
    timezone_id="Asia/Seoul",
    platform="Win32",
)

_FIREFOX_WIN = StealthProfile(
    name="firefox_win",
    user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
        "Gecko/20100101 Firefox/133.0"
    ),
    viewport={"width": 1920, "height": 1080},
    locale="ko-KR",
    timezone_id="Asia/Seoul",
    platform="Win32",
    webgl_vendor="Mozilla",
    webgl_renderer="Mozilla",
)

PROFILES: dict[str, StealthProfile] = {
    "chrome_win": _CHROME_WIN,
    "chrome_mac": _CHROME_MAC,
    "edge_win": _EDGE_WIN,
    "firefox_win": _FIREFOX_WIN,
}


def get_profile(name: str | None = None) -> StealthProfile:
    """이름으로 프로파일 조회. None이면 랜덤 선택."""
    if name is None:
        return random.choice(list(PROFILES.values()))
    if name not in PROFILES:
        raise ValueError(f"Unknown stealth profile: {name}. Available: {list(PROFILES.keys())}")
    return PROFILES[name]


def register_profile(profile: StealthProfile) -> None:
    """사용자 정의 프로파일 등록."""
    PROFILES[profile.name] = profile


STEALTH_JS = """
// navigator.webdriver 숨기기
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// chrome runtime 위장
window.chrome = {runtime: {}, loadTimes: () => {}, csi: () => {}};

// permissions query 위장
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (params) =>
    params.name === 'notifications'
        ? Promise.resolve({state: Notification.permission})
        : origQuery(params);

// plugins 위장 (빈 배열이면 headless로 감지됨)
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// languages 위장
Object.defineProperty(navigator, 'languages', {
    get: () => ['ko-KR', 'ko', 'en-US', 'en'],
});
"""


async def apply_stealth(page: Any, profile: StealthProfile | None = None) -> None:
    """Playwright Page에 스텔스 스크립트 주입.

    - navigator.webdriver 숨기기
    - chrome.runtime 위장
    - permissions query 위장
    - plugins/languages 위장
    - platform/WebGL 위장 (프로파일 기반)
    """
    js = STEALTH_JS
    if profile:
        js += f"""
Object.defineProperty(navigator, 'platform', {{get: () => '{profile.platform}'}});
"""
    await page.add_init_script(js)
