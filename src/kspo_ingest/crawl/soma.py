"""Read-only SOMA list, artwork and map-popup discovery."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from selectolax.parser import HTMLParser

HOST = "soma.kspo.or.kr"
ZONES = ("RED", "BLUE", "YELLOW", "GREEN", "BLACK", "ETC")


def is_board_article(url: str, *, board_source_id: int | None = None) -> bool:
    """Only bulletin articles have an age cutoff; artwork dates are not publication dates."""
    path = urlsplit(url).path
    if urlsplit(url).hostname == HOST:
        return bool(re.match(r"^/(?:customer/notice|draw/notice)/(?:popup/)?\d+(?:/|$)", path))
    return board_source_id is not None or bool(
        re.search(r"/(?:bbs|board)/", path, re.I) and re.search(r"(?:view|detail|\d+)", path, re.I)
    )


def discover_urls(html: str, base_url: str) -> list[str]:
    """Enumerate only public read routes; never execute arbitrary JavaScript."""
    if urlsplit(base_url).hostname != HOST:
        return []
    tree = HTMLParser(html)
    out: set[str] = set()
    path = urlsplit(base_url).path

    def add(value: str) -> None:
        target = urljoin(base_url, value)
        p = urlsplit(target)
        if (
            p.hostname == HOST
            and p.scheme in ("http", "https")
            and not re.search(
                r"/(?:login|logout|insert|update|delete|reserve)(?:/|$)", p.path, re.I
            )
        ):
            out.add(target)

    for ident in re.findall(r"fnSclptrView\(\s*['\"]?(\d+)", html):
        add(f"/piece/product/{ident}")
    # Menu destinations and static popup/window URLs without file extensions.
    for value in re.findall(r"(?:window\.open|\.load)\(\s*['\"]([^'\"]+)['\"]", html):
        if value.startswith(("/", "https://")):
            add(value)
    for ident, category in re.findall(
        r"goDetail\(['\"](\d+)['\"]\s*,\s*['\"]([A-Za-z0-9]+)['\"]", html
    ):
        if path.startswith("/customer/notice/"):
            add(f"/customer/notice/{ident}/{category}")
    for prefix in (
        "/dspy/display/",
        "/dspy/colect/",
        "/class/",
        "/card/news/",
        "/draw/notice/",
        "/draw/collection/",
    ):
        if path.startswith(prefix):
            for ident in re.findall(r"goDetail\(['\"](\d+)['\"]", html):
                add(prefix + ident)
    for ident in re.findall(r"writerDetail\(['\"](\d+)['\"]", html):
        add(f"/draw/writer/{ident}/view")
    if re.fullmatch(r"/draw/writer/\d+/view", path):
        add(path[:-5] + "/product/list")
    for option in tree.css("#select_yr option[value]"):
        year = option.attributes.get("value", "")
        if re.fullmatch(r"\d{4}", year):
            add(f"/dspy/display/{year}/list")
    # GET query preserves the site's list form and cursor, not just page number.
    if "/list" in path and not path.endswith("/zone/list"):
        form = tree.css_first("form#form")
        params = dict(parse_qsl(urlsplit(base_url).query))
        if form:
            for node in form.css("input[name]"):
                if node.attributes.get("type") not in ("checkbox", "radio", "submit", "button"):
                    params[node.attributes["name"]] = node.attributes.get("value", "")
            for node in form.css("select[name]"):
                option = node.css_first("option[selected]") or node.css_first("option")
                if option:
                    params[node.attributes["name"]] = option.attributes.get("value", "")
        for number in re.findall(r"form_goPageIndex\(['\"](\d+)['\"]", html):
            query = dict(params, form_page_index=number)
            p = urlsplit(base_url)
            add(urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), "")))
    if path in ("/", "/main", "/piece/product/list"):
        for zone in ZONES:
            add("/piece/product/zone/list?" + urlencode({"zone": zone, "lastKey": ""}))
            add(f"/piece/product/{zone.lower()}/map")
    for zone, flag, cursor in re.findall(
        r"checkMoreBtn\(\s*['\"]([A-Z]+)['\"]\s*,\s*['\"]([YN])['\"]\s*,\s*['\"]?([^'\"\)]+)", html
    ):
        if zone in ZONES and flag == "Y":
            add("/piece/product/zone/list?" + urlencode({"zone": zone, "lastKey": cursor.strip()}))
    # Map pins reference AJAX fragments. Keep the displayed map number in the URL.
    for pin in tree.css(".park_pin a[data-key]"):
        key = pin.attributes.get("data-key", "")
        if key.isdigit():
            number = pin.text(strip=True)
            add(f"/piece/product/{key}/pop?" + urlencode({"number": number}))
            add(f"/piece/product/{key}")
    for node in tree.css("[onclick]"):
        for ident in re.findall(
            r"(?:fnPop|goPop|openPopup)\(['\"](\d+)['\"]", node.attributes.get("onclick", "")
        ):
            if "/customer/notice" in path:
                add(f"/customer/notice/popup/{ident}")
    return sorted(out)


def popup_content(html: str) -> tuple[str, str] | None:
    """Keep short artwork fields and image metadata that generic density extraction loses."""
    tree = HTMLParser(html)
    layer = tree.css_first(".park_layer") or tree.css_first(".park_layer_inner")
    if layer is None:
        # /pop returns a fragment whose root need not have the outer AJAX container.
        if tree.css_first(".park_layer_close") is None:
            return None
        layer = tree.body or tree.root
    for node in layer.css("script, style, button, .park_layer_close"):
        node.decompose()
    lines = [layer.text(separator="\n", strip=True)]
    title_node = layer.css_first("h3, h4, strong, .tit")
    title = title_node.text(strip=True) if title_node else "조각공원 작품 정보"
    for image in layer.css("img[src]"):
        lines.append("이미지: " + urljoin("https://" + HOST, image.attributes["src"]))
        if image.attributes.get("alt"):
            lines.append("이미지 설명: " + image.attributes["alt"])
    return title, "\n".join(lines)


def detail_content(html: str) -> tuple[str, str] | None:
    """Preserve SOMA detail fields and image descriptions before generic cleanup."""
    popup = popup_content(html)
    if popup:
        return popup
    tree = HTMLParser(html)
    content = tree.css_first("#sub_wrap") or tree.css_first("#fullpage")
    if content is None:
        return None
    title_node = content.css_first(
        ".lv_tit, .ttl h3, .info_writer .name, .view_tit, .view_title, "
        ".board_view .tit, .view_top .tit, .detail_tit, .class_tit"
    ) or tree.css_first("title")
    title = title_node.text(strip=True) if title_node else "소마미술관"
    for node in content.css(
        "script, style, input, select, button, a.writer_sns, .page, .view_page, "
        "#writerList_side, .btn_wrap, .board_prev_next"
    ):
        node.decompose()
    images = []
    for image in content.css("img[src]"):
        images.append("이미지: " + urljoin("https://" + HOST, image.attributes["src"]))
        if image.attributes.get("alt"):
            images.append("이미지 설명: " + image.attributes["alt"])
    # Keep each table row together so labels remain associated with their values.
    for row in content.css("tr"):
        values = [cell.text(separator=" ", strip=True) for cell in row.css("th, td")]
        if values:
            row.replace_with(" | ".join(values) + "\n")
    text = content.text(separator="\n", strip=True)
    if not text:
        return None
    return title, "\n".join([text, *images])
