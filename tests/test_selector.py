"""Tests for crawl.selector — Adaptive CSS selector."""
from __future__ import annotations

import pytest

from kspo_ingest.crawl.selector import (
    AdaptiveSelector,
    ElementFingerprint,
    _extract_fingerprint,
    _similarity,
)


SAMPLE_HTML = """
<html>
<body>
  <div class="product-list">
    <div class="product-card" id="p1" data-id="1">
      <h2 class="title">Product A</h2>
      <span class="price">10,000원</span>
    </div>
    <div class="product-card" id="p2" data-id="2">
      <h2 class="title">Product B</h2>
      <span class="price">20,000원</span>
    </div>
  </div>
</body>
</html>
"""

# DOM이 변경된 버전 — 클래스명/구조 약간 다름
CHANGED_HTML = """
<html>
<body>
  <div class="product-grid">
    <div class="item-card" id="p1" data-id="1">
      <h2 class="item-title">Product A</h2>
      <span class="item-price">10,000원</span>
    </div>
    <div class="item-card" id="p2" data-id="2">
      <h2 class="item-title">Product B</h2>
      <span class="item-price">20,000원</span>
    </div>
  </div>
</body>
</html>
"""


class TestElementFingerprint:
    def test_hash_computed(self):
        fp = ElementFingerprint(
            tag="div",
            attributes={"class": "test"},
            text_preview="hello",
            class_list=["test"],
            parent_tag="body",
            sibling_tags=[],
            child_count=0,
            depth=1,
            css_selector="div.test",
        )
        assert fp.fingerprint_hash
        assert len(fp.fingerprint_hash) == 12


class TestSimilarity:
    def test_identical_fingerprints(self):
        fp = ElementFingerprint(
            tag="div", attributes={"class": "card"}, text_preview="hello",
            class_list=["card"], parent_tag="body", sibling_tags=["span"],
            child_count=2, depth=1, css_selector="div.card",
        )
        assert _similarity(fp, fp) == pytest.approx(1.0)

    def test_different_tags_low_similarity(self):
        fp1 = ElementFingerprint(
            tag="div", attributes={}, text_preview="hello",
            class_list=[], parent_tag="body", sibling_tags=[],
            child_count=0, depth=1, css_selector="div",
        )
        fp2 = ElementFingerprint(
            tag="span", attributes={}, text_preview="hello",
            class_list=[], parent_tag="body", sibling_tags=[],
            child_count=0, depth=1, css_selector="span",
        )
        sim = _similarity(fp1, fp2)
        assert sim < 0.9  # 태그 다름 → 유사도 감소

    def test_same_tag_different_text(self):
        fp1 = ElementFingerprint(
            tag="div", attributes={"class": "card"}, text_preview="Product A",
            class_list=["card"], parent_tag="body", sibling_tags=[],
            child_count=2, depth=1, css_selector="div.card",
        )
        fp2 = ElementFingerprint(
            tag="div", attributes={"class": "card"}, text_preview="Product B",
            class_list=["card"], parent_tag="body", sibling_tags=[],
            child_count=2, depth=1, css_selector="div.card",
        )
        sim = _similarity(fp1, fp2)
        assert sim > 0.7  # 같은 구조, 텍스트만 다름


class TestAdaptiveSelector:
    def test_css_match(self):
        sel = AdaptiveSelector()
        matches = sel.select(SAMPLE_HTML, "div.product-card")
        assert len(matches) == 2
        assert matches[0].method == "css"
        assert matches[0].confidence == 1.0

    def test_css_no_match(self):
        sel = AdaptiveSelector()
        matches = sel.select(SAMPLE_HTML, "div.nonexistent", adaptive=False)
        assert len(matches) == 0

    def test_adaptive_recovery(self):
        sel = AdaptiveSelector()
        # 1차: 원본 HTML에서 fingerprint 저장
        matches1 = sel.select(SAMPLE_HTML, "div.product-card")
        assert len(matches1) == 2

        # 2차: 변경된 HTML — CSS 실패 → adaptive fallback
        matches2 = sel.select(CHANGED_HTML, "div.product-card")
        # div.item-card가 유사하므로 매칭되어야 함
        assert len(matches2) >= 1
        assert matches2[0].method == "adaptive"
        assert matches2[0].confidence >= 0.5

    def test_select_one(self):
        sel = AdaptiveSelector()
        match = sel.select_one(SAMPLE_HTML, "h2.title")
        assert match is not None
        assert "Product A" in match.node.text(strip=True)

    def test_get_text(self):
        sel = AdaptiveSelector()
        text = sel.get_text(SAMPLE_HTML, "h2.title")
        assert text == "Product A"

    def test_get_attribute(self):
        sel = AdaptiveSelector()
        val = sel.get_attribute(SAMPLE_HTML, "div.product-card", "data-id")
        assert val == "1"

    def test_persist_and_restore(self):
        sel = AdaptiveSelector()
        sel.select(SAMPLE_HTML, "div.product-card")
        data = sel.persist()
        assert "div.product-card" in data
        assert len(data["div.product-card"]) == 2

        # 새 인스턴스에 복원
        sel2 = AdaptiveSelector()
        sel2.restore(data)
        assert "div.product-card" in sel2.cached_selectors

        # 복원된 fingerprint로 adaptive 매칭 가능
        matches = sel2.select(CHANGED_HTML, "div.product-card")
        assert len(matches) >= 1

    def test_clear(self):
        sel = AdaptiveSelector()
        sel.select(SAMPLE_HTML, "div.product-card")
        assert len(sel.cached_selectors) == 1
        sel.clear()
        assert len(sel.cached_selectors) == 0

    def test_low_threshold_rejects(self):
        sel = AdaptiveSelector(similarity_threshold=0.99)
        sel.select(SAMPLE_HTML, "div.product-card")
        # 높은 threshold — 구조가 다른 HTML은 매칭 실패
        matches = sel.select(CHANGED_HTML, "div.product-card")
        # class가 많이 다르므로 0.99에는 못 미침
        assert len(matches) == 0
