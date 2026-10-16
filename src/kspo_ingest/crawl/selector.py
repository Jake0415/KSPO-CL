"""Adaptive CSS Selector — DOM 변경에도 요소를 추적하는 적응형 셀렉터.

Scrapling의 Adaptive Parsing 개념을 재설계:
- 요소의 fingerprint(tag, attributes, text, position, siblings)를 저장
- DOM 변경 시 similarity score 기반으로 가장 유사한 요소를 재탐색
- CSS/XPath 실패 시 자동 fallback
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from difflib import SequenceMatcher

from selectolax.parser import HTMLParser, Node


@dataclass
class ElementFingerprint:
    """요소의 구조적 특성 — 재탐색에 사용."""

    tag: str
    attributes: dict[str, str]
    text_preview: str  # 첫 200자
    class_list: list[str]
    parent_tag: str | None
    sibling_tags: list[str]  # 직전/직후 형제
    child_count: int
    depth: int  # 루트로부터의 깊이
    css_selector: str  # 원본 셀렉터
    fingerprint_hash: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint_hash:
            self.fingerprint_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        raw = f"{self.tag}|{sorted(self.attributes.items())}|{self.text_preview[:50]}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]


@dataclass
class SelectorMatch:
    """셀렉터 매칭 결과."""

    node: Node
    method: str  # "css", "xpath", "adaptive"
    confidence: float  # 0.0 ~ 1.0
    fingerprint: ElementFingerprint | None = None


def _extract_fingerprint(node: Node, css_selector: str, depth: int = 0) -> ElementFingerprint:
    """Node에서 fingerprint 추출."""
    attrs = dict(node.attributes) if node.attributes else {}
    text = (node.text(strip=True) or "")[:200]
    class_list = attrs.get("class", "").split() if attrs.get("class") else []

    parent = node.parent
    parent_tag = parent.tag if parent else None

    sibling_tags: list[str] = []
    if parent:
        for child in parent.iter():
            if child != node and hasattr(child, "tag"):
                sibling_tags.append(child.tag)
                if len(sibling_tags) >= 4:
                    break

    child_count = sum(1 for _ in node.iter()) - 1  # 자기 자신 제외

    return ElementFingerprint(
        tag=node.tag,
        attributes=attrs,
        text_preview=text,
        class_list=class_list,
        parent_tag=parent_tag,
        sibling_tags=sibling_tags[:4],
        child_count=child_count,
        depth=depth,
        css_selector=css_selector,
    )


def _similarity(fp1: ElementFingerprint, fp2: ElementFingerprint) -> float:
    """두 fingerprint 간 유사도 (0.0 ~ 1.0)."""
    scores: list[float] = []
    weights: list[float] = []

    # 태그 일치 (가장 중요)
    scores.append(1.0 if fp1.tag == fp2.tag else 0.0)
    weights.append(3.0)

    # 클래스 유사도
    if fp1.class_list or fp2.class_list:
        set1, set2 = set(fp1.class_list), set(fp2.class_list)
        if set1 | set2:
            jaccard = len(set1 & set2) / len(set1 | set2)
            scores.append(jaccard)
        else:
            scores.append(1.0)
    else:
        scores.append(1.0)
    weights.append(2.5)

    # 텍스트 유사도
    text_sim = SequenceMatcher(None, fp1.text_preview[:100], fp2.text_preview[:100]).ratio()
    scores.append(text_sim)
    weights.append(2.0)

    # 부모 태그 일치
    scores.append(1.0 if fp1.parent_tag == fp2.parent_tag else 0.0)
    weights.append(1.5)

    # 속성 키 유사도
    keys1, keys2 = set(fp1.attributes.keys()), set(fp2.attributes.keys())
    if keys1 | keys2:
        scores.append(len(keys1 & keys2) / len(keys1 | keys2))
    else:
        scores.append(1.0)
    weights.append(1.0)

    # 자식 수 유사도
    max_children = max(fp1.child_count, fp2.child_count, 1)
    child_diff = abs(fp1.child_count - fp2.child_count) / max_children
    scores.append(1.0 - child_diff)
    weights.append(0.5)

    # 형제 태그 유사도
    if fp1.sibling_tags or fp2.sibling_tags:
        sib_sim = SequenceMatcher(None, fp1.sibling_tags, fp2.sibling_tags).ratio()
        scores.append(sib_sim)
    else:
        scores.append(1.0)
    weights.append(0.5)

    total = sum(s * w for s, w in zip(scores, weights, strict=True))
    return total / sum(weights)


class AdaptiveSelector:
    """적응형 셀렉터 — CSS 실패 시 fingerprint 기반 재탐색.

    사용법:
        selector = AdaptiveSelector()

        # 최초 선택 — fingerprint 저장
        matches = selector.select(html, "div.product-card")

        # DOM 변경 후 — 같은 셀렉터로 시도, 실패 시 fingerprint로 재탐색
        matches = selector.select(changed_html, "div.product-card")

    fingerprint는 메모리에 캐시. persist()로 직렬화 가능.
    """

    def __init__(self, similarity_threshold: float = 0.65) -> None:
        self._threshold = similarity_threshold
        self._fingerprints: dict[str, list[ElementFingerprint]] = {}

    def select(
        self,
        html: str,
        css_selector: str,
        *,
        adaptive: bool = True,
    ) -> list[SelectorMatch]:
        """CSS 셀렉터로 요소 선택. adaptive=True면 실패 시 fingerprint 기반 재탐색."""
        tree = HTMLParser(html)
        nodes = tree.css(css_selector)

        if nodes:
            matches = []
            fingerprints = []
            for node in nodes:
                fp = _extract_fingerprint(node, css_selector)
                fingerprints.append(fp)
                matches.append(SelectorMatch(
                    node=node,
                    method="css",
                    confidence=1.0,
                    fingerprint=fp,
                ))
            # fingerprint 캐시 갱신
            self._fingerprints[css_selector] = fingerprints
            return matches

        # CSS 실패 — adaptive fallback
        if not adaptive or css_selector not in self._fingerprints:
            return []

        return self._adaptive_search(tree, css_selector)

    def _adaptive_search(self, tree: HTMLParser, css_selector: str) -> list[SelectorMatch]:
        """저장된 fingerprint 기반으로 유사 요소 탐색."""
        stored_fps = self._fingerprints.get(css_selector, [])
        if not stored_fps:
            return []

        matches: list[SelectorMatch] = []

        for stored_fp in stored_fps:
            best_node: Node | None = None
            best_score = 0.0

            # 같은 태그의 모든 요소를 후보로
            candidates = tree.css(stored_fp.tag) or []
            for node in candidates:
                candidate_fp = _extract_fingerprint(node, css_selector)
                score = _similarity(stored_fp, candidate_fp)
                if score > best_score:
                    best_score = score
                    best_node = node

            if best_node is not None and best_score >= self._threshold:
                new_fp = _extract_fingerprint(best_node, css_selector)
                matches.append(SelectorMatch(
                    node=best_node,
                    method="adaptive",
                    confidence=best_score,
                    fingerprint=new_fp,
                ))

        # fingerprint 갱신 (적응)
        if matches:
            self._fingerprints[css_selector] = [
                m.fingerprint for m in matches if m.fingerprint
            ]

        return matches

    def select_one(
        self,
        html: str,
        css_selector: str,
        *,
        adaptive: bool = True,
    ) -> SelectorMatch | None:
        """단일 요소 선택."""
        results = self.select(html, css_selector, adaptive=adaptive)
        return results[0] if results else None

    def get_text(
        self,
        html: str,
        css_selector: str,
        *,
        adaptive: bool = True,
        separator: str = "\n",
    ) -> str | None:
        """요소의 텍스트 추출."""
        match = self.select_one(html, css_selector, adaptive=adaptive)
        if match is None:
            return None
        return match.node.text(separator=separator, strip=True)

    def get_attribute(
        self,
        html: str,
        css_selector: str,
        attr: str,
        *,
        adaptive: bool = True,
    ) -> str | None:
        """요소의 속성값 추출."""
        match = self.select_one(html, css_selector, adaptive=adaptive)
        if match is None:
            return None
        attrs = match.node.attributes
        return attrs.get(attr) if attrs else None

    def persist(self) -> dict[str, list[dict]]:
        """fingerprint를 직렬화 가능한 dict로 반환."""
        out: dict[str, list[dict]] = {}
        for selector, fps in self._fingerprints.items():
            out[selector] = [
                {
                    "tag": fp.tag,
                    "attributes": fp.attributes,
                    "text_preview": fp.text_preview,
                    "class_list": fp.class_list,
                    "parent_tag": fp.parent_tag,
                    "sibling_tags": fp.sibling_tags,
                    "child_count": fp.child_count,
                    "depth": fp.depth,
                    "css_selector": fp.css_selector,
                    "fingerprint_hash": fp.fingerprint_hash,
                }
                for fp in fps
            ]
        return out

    def restore(self, data: dict[str, list[dict]]) -> None:
        """persist()의 결과를 복원."""
        for selector, fps_data in data.items():
            self._fingerprints[selector] = [
                ElementFingerprint(**fp_dict) for fp_dict in fps_data
            ]

    @property
    def cached_selectors(self) -> list[str]:
        return list(self._fingerprints.keys())

    def clear(self) -> None:
        self._fingerprints.clear()
