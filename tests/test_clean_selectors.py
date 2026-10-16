from __future__ import annotations

from kspo_ingest.clean.selectors import apply_blacklist, load_global_selectors


def test_load_global_selectors_returns_list():
    sels = load_global_selectors()
    assert isinstance(sels, list)
    assert len(sels) > 0
    assert "header" in sels
    assert "footer" in sels


def test_apply_blacklist_decomposes_matched_nodes():
    html = '<html><body><nav>menu</nav><main>real body</main><footer>foot</footer></body></html>'
    out = apply_blacklist(html, ["nav", "footer"], None)
    assert "menu" not in out
    assert "foot" not in out
    assert "real body" in out


def test_apply_blacklist_with_domain_selectors():
    html = '<html><body><div class="ad">광고</div><main>본문</main></body></html>'
    out = apply_blacklist(html, [], [".ad"])
    assert "광고" not in out
    assert "본문" in out


def test_apply_blacklist_global_and_domain_combined():
    html = '<html><body><nav>nav</nav><div class="x">domain</div><main>main</main></body></html>'
    out = apply_blacklist(html, ["nav"], [".x"])
    assert "nav" not in out
    assert "domain" not in out
    assert "main" in out


def test_apply_blacklist_invalid_selector_ignored():
    """문법 오류가 있는 selector가 섞여 있어도 다른 selector는 정상 동작."""
    html = '<html><body><nav>nav</nav><main>main</main></body></html>'
    out = apply_blacklist(html, ["???invalid???", "nav"], None)
    assert "nav" not in out
    assert "main" in out


def test_apply_blacklist_no_match_returns_original():
    html = "<html><body><main>본문</main></body></html>"
    out = apply_blacklist(html, [".nonexistent"], None)
    assert "본문" in out
