from __future__ import annotations

from pathlib import Path

import yaml
from selectolax.parser import HTMLParser

from kspo_ingest.observability.logger import get_logger

log = get_logger("clean", "selectors")


_DEFAULT_CONFIG = (
    Path(__file__).resolve().parent.parent.parent.parent / "configs" / "selectors.yaml"
)


def load_global_selectors(path: Path | None = None) -> list[str]:
    p = path or _DEFAULT_CONFIG
    if not p.exists():
        log.bind(event="selectors_missing", path=str(p)).warning("configs/selectors.yaml 미존재")
        return []
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    if not isinstance(data, list):
        log.bind(event="selectors_invalid_format").warning("selectors.yaml은 list 여야 합니다")
        return []
    return [str(s) for s in data]


def apply_blacklist(
    html: str, global_selectors: list[str], domain_selectors: list[str] | None
) -> str:
    """selectolax로 매칭 노드 .decompose() 후 HTML 반환."""
    tree = HTMLParser(html, detect_encoding=False, use_meta_tags=False)
    selectors = [*global_selectors, *(domain_selectors or [])]
    for sel in selectors:
        try:
            for node in tree.css(sel):
                node.decompose()
        except Exception as e:
            log.bind(event="selector_skip", selector=sel, error=str(e)).warning(
                "잘못된 selector — 무시"
            )
    # selectolax의 .html 게터는 비-UTF-8 바이트가 섞인 문서에서 UnicodeDecodeError를
    # 던질 수 있다(EUC-KR 등 인코딩 오검출 페이지). 크래시 대신 원본 html로 폴백.
    try:
        return tree.html or html
    except (UnicodeDecodeError, ValueError):
        log.bind(event="blacklist_html_decode_fail").warning(
            "tree.html 디코딩 실패 — 원본 html 폴백"
        )
        return html
