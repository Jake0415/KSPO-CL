"""Bounded read-only browser expansion, AJAX capture and coverage evidence."""

from __future__ import annotations

import asyncio
import hashlib
import html as html_escape
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from selectolax.parser import HTMLParser

from kspo_ingest.crawl.readiness import ContentReadinessError, ContentWaiter, ReadinessPolicy

_READ_LABEL = re.compile(
    r"더\s*보기|펼치|확장|상세|다음|조회|메뉴|\+|more|expand|next|details", re.I
)
_WRITE = re.compile(
    r"login|logout|sign.?in|sign.?up|delete|remove|insert|update|save|submit|reserve|apply|"
    r"purchase|payment|booking|등록|삭제|저장|예약|신청|결제|로그인",
    re.I,
)
_SELECTOR = 'select, button, [role="tab"], [role="button"], a[href^="#"], a[href^="javascript:"]'


_SEARCH_ACTION = re.compile(r"검색|조회|search|query|findAddress|findPost|zipCode|postcode", re.I)
_TEXT_INPUT = 'input:not([type]), input[type="text"], input[type="search"], textarea'


def _requires_user_search(node, tree) -> bool:
    """Keep search screens, but never run or alter user-input search forms."""
    attrs = node.attributes
    signal = " ".join(
        [
            node.text(strip=True),
            *((attrs.get(k) or "") for k in ("aria-label", "title", "onclick", "onchange", "href")),
        ]
    )
    # An explicit search action is not a content expansion, even outside a form.
    if _SEARCH_ACTION.search(signal) and node.tag != "select":
        return True
    form_id = attrs.get("form")
    if form_id:
        for form in tree.css("form"):
            if form.attributes.get("id") == form_id and form.css_first(_TEXT_INPUT):
                return True
    parent = node.parent
    while parent is not None and parent.tag not in ("body", "html"):
        if parent.tag == "form" and parent.css_first(_TEXT_INPUT):
            return True
        # Also cover script-driven search widgets without a form element.
        if parent.tag in ("div", "section") and parent.css_first(_TEXT_INPUT):
            name = " ".join((parent.attributes.get(k) or "") for k in ("id", "class", "role"))
            if re.search(r"search|query|postcode|zipcode|검색", name, re.I):
                return True
        parent = parent.parent
    return False


def interaction_candidates(html: str) -> list[dict[str, str | bool]]:
    result = []
    tree = HTMLParser(html)
    nodes = (
        node
        for node in tree.css("*")
        if (
            node.tag in ("button", "select")
            or node.attributes.get("role") in ("tab", "button")
            or (
                node.tag == "a"
                and (node.attributes.get("href") or "").startswith(("#", "javascript:"))
            )
        )
    )
    for index, node in enumerate(nodes):
        attrs = node.attributes
        if _requires_user_search(node, tree):
            continue
        label = (attrs.get("aria-label") or attrs.get("title") or node.text(strip=True))[:160]
        signal = " ".join([label, (attrs.get("onclick") or ""), (attrs.get("href") or "")])
        expanded = attrs.get("aria-expanded")
        tab = (
            attrs.get("role") == "tab"
            or attrs.get("data-toggle") == "tab"
            or bool(re.search(r"(?:changeTab|fnTab|selectTab)\s*\(", (attrs.get("onclick") or "")))
        )
        if node.tag == "select":
            if _WRITE.search(signal + " " + (attrs.get("onchange") or "")):
                continue
            for option in node.css("option[value]"):
                value = option.attributes.get("value") or ""
                option_label = option.text(strip=True)
                if not value or "selected" in option.attributes or "disabled" in option.attributes:
                    continue
                if _WRITE.search(option_label + " " + value):
                    continue
                result.append(
                    {
                        "index": str(index),
                        "label": label[:40] + ":" + option_label,
                        "repeat": False,
                        "option": value,
                    }
                )
            continue
        if _WRITE.search(signal) or attrs.get("type") == "submit":
            continue
        if expanded == "true" or attrs.get("aria-selected") == "true":
            continue
        # Navigation anchors only: do not expand arbitrary JavaScript actions.
        parent = node.parent
        navigation = False
        navigation_root = None
        while parent is not None:
            if parent.tag in ("nav", "header") or parent.attributes.get("id") in (
                "topNav",
                "gnb",
                "header",
            ):
                navigation = True
                navigation_root = parent
                break
            parent = parent.parent
        nav_link = navigation and node.tag == "a" and bool(label)
        if not (tab or expanded == "false" or _READ_LABEL.search(label) or nav_link):
            continue
        result.append(
            {
                "index": str(index),
                "label": label,
                "navigation_key": (
                    hashlib.sha256(
                        (
                            navigation_root.text(separator=" ", strip=True)
                            + "|"
                            + signal
                            + "|"
                            + repr(
                                [
                                    (
                                        n.tag,
                                        {
                                            k: v
                                            for k, v in n.attributes.items()
                                            if k
                                            not in {
                                                "class",
                                                "style",
                                                "hidden",
                                                "aria-expanded",
                                                "aria-selected",
                                            }
                                        },
                                    )
                                    for n in navigation_root.css("*")
                                ]
                            )
                        ).encode()
                    ).hexdigest()
                    if navigation_root is not None
                    and not tab
                    and (
                        node.tag == "a"
                        or (node.tag == "button" and re.search(r"메뉴|menu", label, re.I))
                    )
                    else ""
                ),
                "navigation_menu": bool(
                    navigation_root is not None
                    and re.fullmatch(
                        r"전체\s*메뉴|메뉴\s*(?:닫기|열기)|(?:open|close)?\s*menu", label, re.I
                    )
                ),
                "repeat": bool(re.search(r"더\s*보기|more|next|다음", label, re.I)),
            }
        )
    return result


def has_dynamic_controls(html: str) -> bool:
    return bool(interaction_candidates(html))


def navigation_depth(source: str, target: str, depth: int) -> int:
    a, b = urlsplit(source), urlsplit(target)
    if (a.hostname, a.path) == (b.hostname, b.path):
        pa, pb = (
            parse_qs(a.query, keep_blank_values=True),
            parse_qs(b.query, keep_blank_values=True),
        )
        cursor_keys = {
            "page",
            "pageno",
            "pageindex",
            "form_page_index",
            "lastkey",
            "offset",
            "cursor",
        }
        changed = {key.lower() for key in set(pa) | set(pb) if pa.get(key) != pb.get(key)}
        form_keys = {
            "_form_id",
            "dummy",
            "form_page_list_count",
            "form_pc_page_count",
            "form_mb_page_count",
        }
        if changed & cursor_keys and changed <= cursor_keys | form_keys:
            return depth
    return depth + 1


def snapshot_content(html: str) -> str:
    tree = HTMLParser(html)
    root = tree.css_first('main, article, #sub_wrap, #fullpage, [role="main"]') or tree.body
    if root is None:
        return ""
    for node in root.css("script, style, nav, header, footer"):
        node.decompose()
    text = root.text(separator="\n", strip=True)
    links = [(node.attributes.get("href") or "") for node in root.css("a[href]")]
    return text + "\n" + "\n".join(links) if text or links else ""


def ajax_text(data: object) -> str:
    """Keep textual JSON content; avoid serializing tokens and opaque numeric IDs."""
    if isinstance(data, str):
        return snapshot_content(data) if "<" in data else data
    if isinstance(data, list):
        return "\n".join(filter(None, (ajax_text(value) for value in data)))
    if isinstance(data, dict):
        fields = []
        for key, value in data.items():
            if re.search(r"token|password|secret|cookie|session|email", key, re.I):
                continue
            text = ajax_text(value)
            if text:
                fields.append(f"{key}: {text}")
        return "\n".join(fields)
    return ""


async def expand_readonly(
    page,
    *,
    max_actions: int = 100,
    navigation_cache: dict[str, set[str]] | None = None,
    capture_initial: bool = True,
    readiness_policy: ReadinessPolicy | None = None,
) -> tuple[str, dict]:
    host = urlsplit(page.url).hostname
    original_url = page.url
    initial = await page.content()
    baseline = snapshot_content(initial)
    observations: list[str] = []
    observed: set[str] = {baseline}
    ajax_urls: list[str] = []
    tasks: list = []
    revealed_links: set[str] = set()
    report = {
        "candidate_count": 0,
        "clicked": 0,
        "no_change": 0,
        "failures": [],
        "limit_reached": False,
        "ajax_urls": ajax_urls,
        "blocked_requests": [],
        "hidden": [],
    }

    async def guard(route):
        request = route.request
        parsed = urlsplit(request.url)
        # Public navigation often uses arbitrary POST endpoint names.
        # Allow same-host POST unless the path explicitly denotes a write action.
        read_post = (
            request.method == "POST" and parsed.hostname == host and not _WRITE.search(parsed.path)
        )
        if (
            _WRITE.search(parsed.path) or request.method not in ("GET", "HEAD", "OPTIONS")
        ) and not read_post:
            report["blocked_requests"].append(request.url)
            await route.abort()
            return
        await route.continue_()

    async def capture(response):
        if urlsplit(response.url).hostname != host or response.status != 200:
            return
        if response.request.resource_type not in ("xhr", "fetch"):
            return
        try:
            raw = await response.body()
            if len(raw) > 1024 * 1024:
                report["failures"].append("ajax_too_large")
                return
            ct = response.headers.get("content-type", "")
            if "json" in ct:
                text = ajax_text(json.loads(raw))
            elif "html" in ct:
                text = snapshot_content(raw.decode("utf-8", errors="replace"))
            else:
                return
            if text.strip() and text not in observed:
                observations.append(text)
                observed.add(text)
                ajax_urls.append(response.url)
        except Exception as exc:
            report["failures"].append("ajax_" + type(exc).__name__)

    def on_response(response):
        if len(tasks) >= 200:
            report["limit_reached"] = True
            return
        tasks.append(asyncio.create_task(capture(response)))

    await page.route("**/*", guard)
    page.on("response", on_response)
    waiter = ContentWaiter(page, readiness_policy).start()
    tried: set[str] = set()
    visited_states = {snapshot_content(initial)}
    try:
        if capture_initial:
            # Listener is now attached: capture AJAX fired on initial page load too.
            await page.reload(wait_until="domcontentloaded", timeout=15000)
            report["initial_readiness"] = await waiter.wait(initial=True)
            initial = await page.content()
        for _ in range(max_actions):
            current = await page.content()
            candidates = interaction_candidates(current)
            report["candidate_count"] = max(report["candidate_count"], len(candidates))
            eligible = [c for c in candidates if c["label"] + ":" + c["index"] not in tried]
            if not eligible:
                break
            candidate = eligible[0]
            key = candidate["label"] + ":" + candidate["index"]
            nav_key = candidate.get("navigation_key")
            cache_key = f"{urljoin(original_url, chr(46))}:{nav_key}"
            if nav_key and navigation_cache is not None and cache_key in navigation_cache:
                revealed_links.update(navigation_cache[cache_key])
                tried.add(key)
                report["navigation_cache_hits"] = report.get("navigation_cache_hits", 0) + 1
                continue
            control = page.locator(_SELECTOR).nth(int(candidate["index"]))
            try:
                if not await control.is_visible():
                    report["hidden"].append(str(candidate["label"]))
                    tried.add(key)
                    continue
                # is_visible() ignores overlays and offscreen/closed menu panels.
                # Avoid spending the click timeout on controls that cannot receive input.
                await control.scroll_into_view_if_needed(timeout=1500)
                hit = await control.evaluate("""el => {
                    const r = el.getBoundingClientRect();
                    const left = Math.max(0, r.left), right = Math.min(innerWidth, r.right);
                    const topY = Math.max(0, r.top), bottom = Math.min(innerHeight, r.bottom);
                    const x = left + (right - left) / 2, y = topY + (bottom - topY) / 2;
                    const top = document.elementFromPoint(x, y);
                    return {clickable: !!top && (top === el || el.contains(top)),
                            blocker: top ? top.tagName.toLowerCase() : "outside_viewport"};
                }""")
                if not hit["clickable"]:
                    report.setdefault("obstructed_controls", []).append(
                        {"action": str(candidate["label"]), "blocker": hit["blocker"]}
                    )
                    tried.add(key)
                    continue
                before = snapshot_content(current)
                before_document = await waiter.snapshot()
                if candidate.get("option") is not None:
                    await control.select_option(str(candidate["option"]), timeout=2500)
                else:
                    await control.click(timeout=2500, no_wait_after=True)
                report["clicked"] += 1
                ready = await waiter.wait(initial=False, before=before_document)
                report.setdefault("readiness", []).append(ready)
                if page.url != original_url:
                    if urlsplit(page.url).hostname == host and not _WRITE.search(
                        urlsplit(page.url).path
                    ):
                        revealed_links.add(page.url)
                        if nav_key and navigation_cache is not None:
                            navigation_cache[cache_key] = {page.url}
                    await page.goto(original_url, wait_until="domcontentloaded", timeout=15000)
                    await waiter.wait(initial=True)
                    tried.add(key)
                    report.setdefault("navigations", []).append(str(candidate["label"]))
                    continue
                revealed_html = await page.content()
                for anchor in HTMLParser(revealed_html).css("a[href]"):
                    target = urljoin(original_url, anchor.attributes.get("href", ""))
                    if (
                        urlsplit(target).hostname == host
                        and not _WRITE.search(urlsplit(target).path)
                        and urlsplit(target).scheme in ("http", "https")
                    ):
                        revealed_links.add(target)
                if nav_key and navigation_cache is not None:

                    def body_without_navigation(markup):
                        tree = HTMLParser(markup)
                        for node in tree.css("nav,header,footer,#gnb,#topNav,#header"):
                            node.decompose()
                        return tree.text(separator=" ", strip=True)

                    if candidate.get("navigation_menu") or body_without_navigation(
                        current
                    ) == body_without_navigation(revealed_html):
                        navigation_tree = HTMLParser(revealed_html)
                        navigation_cache[cache_key] = {
                            urljoin(original_url, a.attributes.get("href") or "")
                            for a in navigation_tree.css(
                                "nav a[href],header a[href],#gnb a[href],"
                                "#topNav a[href],#header a[href]"
                            )
                            if urlsplit(
                                urljoin(original_url, a.attributes.get("href") or "")
                            ).scheme
                            in ("http", "https")
                            and urlsplit(
                                urljoin(original_url, a.attributes.get("href") or "")
                            ).hostname
                            == host
                        }
                content = snapshot_content(revealed_html)
                if content != before:
                    if content in visited_states:
                        tried.add(key)
                        report["repeated_states"] = report.get("repeated_states", 0) + 1
                        continue
                    visited_states.add(content)
                    if content not in observed:
                        observations.append(content)
                        observed.add(content)
                    if not candidate["repeat"]:
                        tried.add(key)
                else:
                    report["no_change"] += 1
                    tried.add(key)
            except Exception as exc:
                if isinstance(exc, ContentReadinessError):
                    report.setdefault("readiness_failures", []).append(
                        {
                            "action": str(candidate["label"]),
                            "error": str(exc)[:300],
                        }
                    )
                report["failures"].append(str(candidate["label"]) + ":" + type(exc).__name__)
                tried.add(key)
                # A failed navigation can leave Chromium on chrome-error://. Restore
                # before inspecting another control; retain the valid initial HTML.
                if page.url != original_url:
                    try:
                        await page.goto(original_url, wait_until="domcontentloaded", timeout=15000)
                        await waiter.wait(initial=True)
                        report["recovered_navigations"] = report.get("recovered_navigations", 0) + 1
                    except Exception as recovery_exc:
                        report["failures"].append("restore:" + type(recovery_exc).__name__)
                        report["stop_reason"] = "restore_failed"
                        break
        else:
            report["limit_reached"] = True
    finally:
        waiter.close()
        page.remove_listener("response", on_response)
        await page.unroute("**/*", guard)
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=10)
            except TimeoutError:
                report["failures"].append("ajax_timeout")
    report["needs_review"] = bool(
        report["failures"]
        or report["hidden"]
        or report["limit_reached"]
        or report["blocked_requests"]
        or report.get("obstructed_controls")
        or report.get("repeated_states")
    )
    report["revealed_links"] = sorted(revealed_links)
    report["captured_blocks"] = len(observations)
    blocks = "".join(
        '<section data-rag-dynamic="true"><pre>' + html_escape.escape(text) + "</pre></section>"
        for text in observations
    )
    blocks += (
        '<section data-rag-links="true">'
        + "".join(
            '<a href="' + html_escape.escape(url, quote=True) + '">동적 링크</a>'
            for url in sorted(revealed_links)
        )
        + "</section>"
    )
    # Keep the initial DOM and all newly revealed source facts, even after tabs hide them.
    return initial.replace(
        "</body>", blocks + "</body>"
    ) if "</body>" in initial else initial + blocks, report
