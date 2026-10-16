"""Adaptive Selector 예제 — DOM 변경에도 요소 추적."""
from kspo_ingest.crawl.selector import AdaptiveSelector

# 원본 HTML
original = """
<div class="news-list">
  <div class="news-item" data-id="1">
    <h3 class="news-title">공지사항 제목 1</h3>
    <span class="news-date">2026-07-01</span>
  </div>
  <div class="news-item" data-id="2">
    <h3 class="news-title">공지사항 제목 2</h3>
    <span class="news-date">2026-07-02</span>
  </div>
</div>
"""

# DOM이 변경된 HTML (클래스명 변경, 구조 유사)
changed = """
<div class="notice-grid">
  <div class="notice-card" data-id="1">
    <h3 class="card-title">공지사항 제목 1</h3>
    <span class="card-date">2026-07-01</span>
  </div>
  <div class="notice-card" data-id="2">
    <h3 class="card-title">공지사항 제목 2</h3>
    <span class="card-date">2026-07-02</span>
  </div>
</div>
"""


def main():
    selector = AdaptiveSelector(similarity_threshold=0.6)

    # 1차: 원본 HTML에서 요소 선택 → fingerprint 저장
    print("=== 원본 HTML ===")
    matches = selector.select(original, "div.news-item")
    for m in matches:
        text = m.node.text(strip=True)[:60]
        print(f"  [{m.method}] confidence={m.confidence:.2f} text='{text}'")

    # 2차: DOM 변경 후 — CSS 실패 → adaptive fallback
    print("\n=== 변경된 HTML (adaptive) ===")
    matches2 = selector.select(changed, "div.news-item")
    for m in matches2:
        text = m.node.text(strip=True)[:60]
        print(f"  [{m.method}] confidence={m.confidence:.2f} text='{text}'")

    # fingerprint 직렬화
    data = selector.persist()
    print(f"\n캐시된 셀렉터: {selector.cached_selectors}")
    print(f"Fingerprint 수: {sum(len(fps) for fps in data.values())}")


if __name__ == "__main__":
    main()
