from __future__ import annotations

from qdrant_client import AsyncQdrantClient

from kspo_ingest.observability.logger import get_logger
from kspo_ingest.settings import settings

log = get_logger("qdrant", "client")

_client: AsyncQdrantClient | None = None
_logged_connect = False


def _detect_mode(url: str) -> str:
    """compose service name 'qdrant' 포함이면 self_hosted, 그 외 external."""
    return "self_hosted" if "qdrant" in url else "external"


def get_client() -> AsyncQdrantClient:
    """AsyncQdrantClient 싱글톤. settings.qdrant_url + settings.qdrant_api_key."""
    global _client, _logged_connect
    if _client is None:
        _client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
            timeout=30.0,
        )
    if not _logged_connect:
        log.bind(
            event="qdrant_connect",
            url=settings.qdrant_url,
            mode=_detect_mode(settings.qdrant_url),
        ).info("qdrant client initialized")
        _logged_connect = True
    return _client


def reset_client_for_tests() -> None:
    """테스트 간 격리용 — 싱글톤 + log flag 초기화."""
    global _client, _logged_connect
    _client = None
    _logged_connect = False


def get_mode() -> str:
    return _detect_mode(settings.qdrant_url)
