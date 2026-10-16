from __future__ import annotations

# 확장자 → MIME type 매핑. 다운로드를 안 하므로 응답 헤더가 없음 — URL/링크만으로 추정.
# `mimetypes` 표준 모듈은 OS 의존적이고 한글 .hwp/.hwpx를 인식 못 하므로 명시 매핑 사용.
_MIME_BY_EXT: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".ppt": "application/vnd.ms-powerpoint",
    ".hwp": "application/vnd.hancom.hwp",
    ".hwpx": "application/vnd.hancom.hwpx",
    ".zip": "application/zip",
    ".txt": "text/plain",
}


def mime_for_ext(ext: str) -> str:
    """확장자(.pdf 등) → MIME. 미등록은 octet-stream."""
    return _MIME_BY_EXT.get(ext.lower(), "application/octet-stream")
