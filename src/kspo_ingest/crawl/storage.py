from __future__ import annotations

import os
from pathlib import Path


def raw_path(storage_root: Path, domain_id: int, url_hash: str) -> Path:
    """{root}/raw/{domain_id}/{url_hash[:2]}/{url_hash}.html — 1단계 sharding."""
    return storage_root / "raw" / str(domain_id) / url_hash[:2] / f"{url_hash}.html"


def refined_path(storage_root: Path, page_id: int, suffix: str = "page.json") -> Path:
    """{root}/refined/{page_id}/{suffix}."""
    return storage_root / "refined" / str(page_id) / suffix


def attachment_path(storage_root: Path, domain_id: int, file_hash: str, ext: str) -> Path:
    """{root}/attachments/{domain_id}/{file_hash[:2]}/{file_hash}.{ext}."""
    ext = ext.lstrip(".") or "bin"
    return storage_root / "attachments" / str(domain_id) / file_hash[:2] / f"{file_hash}.{ext}"


async def save_atomic(path: Path, body: bytes) -> None:
    """tmp 파일에 쓰고 rename — 부분 쓰기 방지. 디렉터리 자동 생성."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(body)
    os.replace(tmp, path)
