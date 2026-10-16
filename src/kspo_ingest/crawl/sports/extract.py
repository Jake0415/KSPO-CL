"""HTML extraction for sports.re.kr templates (selectolax).

Selectors verified against live HTML 2026-07-06:
  board detail : .bbs_view_v4 (TH 제목/조회수/등록일/첨부) + .context + .attachWrap
  static page  : div.subContent (h2/h3/h4 titles + body)
  research     : metadata table (제목/영문제목/책임저자/보고서구분/발행연도/원문)
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from selectolax.parser import HTMLParser

from kspo_ingest.attach.mime import mime_for_ext

from . import patterns as P

_WS = re.compile(r"\s+")

# Non-content nodes whose text() must never leak into a document body.
# selectolax .text() includes <style>/<script> text verbatim, which is how raw
# CSS/JS leaked into gallery-board bodies (audit 2026-07-08).
_NOISE_SELECTOR = "style, script, noscript"


def _norm(s: str | None) -> str:
    return _WS.sub(" ", (s or "").strip())


def _clean_text(node) -> str:
    """Text of a node with <style>/<script>/<noscript> stripped first.

    Rule: body text is only ever taken from a content node via this helper —
    never from a raw .text() that can carry template chrome / stylesheets.
    """
    if node is None:
        return ""
    for bad in node.css(_NOISE_SELECTOR):
        bad.decompose()
    return _norm(node.text())


def _ext_of(name: str | None) -> str:
    """Lowercased extension (with dot) of a filename, else ''."""
    if not name or "." not in name:
        return ""
    return name[name.rfind("."):].lower()


# --- list rows ----------------------------------------------------------------
def extract_board_row_ids(html: str) -> list[str]:
    """con_seq values from fnBoardContentView('N') in list rows (dedup, ordered)."""
    out, seen = [], set()
    for m in P.RE_BOARD_VIEW.finditer(html):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(m.group(1))
    return out


def extract_board_rows(html: str) -> list[tuple[str, str]]:
    """(con_seq, title) from list rows. The list is the authoritative source of
    titles (some detail templates omit a clear title). Ordered, deduped."""
    tree = HTMLParser(html)
    out, seen = [], set()
    for a in tree.css("a"):
        href = a.attributes.get("href") or ""
        m = P.RE_BOARD_VIEW.search(href)
        if not m:
            continue
        cid = m.group(1)
        if cid in seen:
            continue
        seen.add(cid)
        out.append((cid, _norm(a.text())))
    return out


def extract_media_rows(html: str) -> list[dict]:
    """KISS미디어룸 (ns board): rows are external press links, not internal
    detail pages. Capture (title, external_url, posted_at) from the list."""
    tree = HTMLParser(html)
    rows = []
    body = tree.css_first("table tbody") or tree
    for tr in body.css("tr"):
        # external URL: first http anchor that leaves this host
        url = None
        for a in tr.css("a[href^=http]"):
            href = a.attributes.get("href") or ""
            if href and P.HOST not in href:
                url = href
                break
        if not url:
            continue
        cells = [_norm(td.text()) for td in tr.css("td")]
        date = next((c for c in cells if _DATE.search(c)), None)
        # title = longest cell that is neither a bare number nor a date
        title_cells = [c for c in cells
                       if c and not c.isdigit() and not _DATE.fullmatch(c)]
        title = max(title_cells, key=len) if title_cells else ""
        rows.append({
            "title": title,
            "external_url": url,
            "posted_at": _DATE.search(date).group(0) if date else None,
        })
    return rows


def extract_faq_items(html: str) -> list[dict]:
    """FAQ (fq board) is an accordion; capture Q/A pairs from the list page."""
    tree = HTMLParser(html)
    items = []
    for dl in tree.css("dl"):
        q = dl.css_first("dt")
        a = dl.css_first("dd")
        if q and _norm(q.text()):
            items.append({"q": _norm(q.text()), "a": _norm(a.text()) if a else ""})
    if not items:  # fallback: li-based accordions
        for li in tree.css(".faq_list li, .accordion li, ul.faq li"):
            t = _norm(li.text())
            if t:
                items.append({"q": t[:120], "a": t})
    return items


def _rows_from_onclick(html: str, id_regex) -> list[tuple[str, str]]:
    """Generic (id, title) extractor for rows whose anchor carries
    onclick="fnDetail('ID', ...)". Title = anchor text."""
    tree = HTMLParser(html)
    out, seen = [], set()
    for a in tree.css("a[onclick]"):
        oc = a.attributes.get("onclick") or ""
        m = id_regex.search(oc)
        if not m:
            continue
        rid = m.group(1)
        if rid in seen:
            continue
        seen.add(rid)
        out.append((rid, _norm(a.text())))
    return out


def extract_research_rows(html: str) -> list[tuple[str, str]]:
    """(artctrlno, title) from research/pub list rows (fnDetail(art,bib,lib))."""
    return _rows_from_onclick(html, P.RE_FNDETAIL_ART)


def extract_bid_rows(html: str) -> list[tuple[str, str]]:
    """(num_p, title) from bid list rows (fnDetail(num_p))."""
    return _rows_from_onclick(html, P.RE_FNDETAIL_NUM)


def extract_research_ids(html: str) -> list[str]:
    """artctrlno values from research/pub list rows (fnDetail onclick)."""
    return [rid for rid, _ in extract_research_rows(html)]


def extract_voc_ids(html: str) -> list[str]:
    out, seen = [], set()
    for m in P.RE_VOC_VIEW.finditer(html):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(m.group(1))
    return out


def extract_voc_rows(html: str) -> list[tuple[str, str]]:
    """(voc_id, title) from VOC list rows (href=javascript:fnVocView('VB..'))."""
    tree = HTMLParser(html)
    out, seen = [], set()
    for a in tree.css("a"):
        href = a.attributes.get("href") or ""
        m = P.RE_VOC_VIEW.search(href)
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        out.append((m.group(1), _norm(a.text())))
    return out


# --- attachments --------------------------------------------------------------
@dataclass
class Attachment:
    kind: str          # cms_file | pyxis_file
    download_url: str
    display_name: str
    stored_name: str
    mime: str = "application/octet-stream"


def _mime_for(*names: str) -> str:
    """MIME from the first name that carries a known extension."""
    for n in names:
        ext = _ext_of(n)
        if ext:
            return mime_for_ext(ext)
    return "application/octet-stream"


def extract_attachments(html: str) -> list[Attachment]:
    out: list[Attachment] = []
    seen: set[str] = set()
    for path, disp, stored in P.RE_FILE_DOWN.findall(html):
        if stored in seen:
            continue
        seen.add(stored)
        out.append(Attachment(
            kind="cms_file",
            download_url=P.file_download_url(path, stored),
            display_name=_norm(disp),
            stored_name=stored,
            mime=_mime_for(stored, disp),
        ))
    for uuid in P.RE_PYXIS.findall(html):
        url = f"{P.BASE}/pyxis-api/1/digital-files/{uuid}"
        if url in seen:
            continue
        seen.add(url)
        out.append(Attachment(kind="pyxis_file", download_url=url,
                              display_name="", stored_name=uuid,
                              mime="application/octet-stream"))
    return out


# --- detail documents ---------------------------------------------------------
@dataclass
class Document:
    unit_type: str
    title: str = ""
    body_text: str = ""
    posted_at: str | None = None
    meta: dict = field(default_factory=dict)
    attachments: list[Attachment] = field(default_factory=list)
    content_hash: str = ""


def _hash(body: str, atts: list[Attachment]) -> str:
    h = hashlib.sha256()
    h.update(_norm(body).encode("utf-8"))
    for a in sorted(atts, key=lambda x: x.stored_name):
        h.update(b"\x00")
        h.update(a.stored_name.encode("utf-8"))
    return h.hexdigest()


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Date row labels across sports.re.kr templates (board 등록일/작성일, bid 공고일/게시일).
_DATE_LABELS = ("등록일", "작성일", "공고일", "게시일", "등록일자", "작성일자", "공고일자")


def extract_board_detail(html: str, list_title: str = "",
                        unit_type: str = "board") -> Document:
    """Handles the `.bbs_view_v4` template (boards AND bid) plus the
    gallery/webzine template (`.cont_txt`/`.cont_sub`/`.gal-tit`, boards 60/70).

    Volatile fields (조회수 view-count) are read into meta but NEVER into
    body/content_hash, so an unchanged post re-hashes identically. `list_title`
    from the list row is the authoritative title fallback.
    """
    tree = HTMLParser(html)
    v = tree.css_first(".bbs_view_v4")
    title, posted, views = "", None, None
    if v:
        kv_nodes = {}
        for tr in v.css("tr"):
            cells = tr.css("th, td")
            i = 0
            while i < len(cells) - 1:
                if cells[i].tag == "th" and cells[i + 1].tag == "td":
                    lbl = _norm(cells[i].text())
                    if lbl and lbl not in kv_nodes:
                        kv_nodes[lbl] = cells[i + 1]
                    i += 2
                else:
                    i += 1
        title = _norm(kv_nodes["제목"].text()) if "제목" in kv_nodes else ""
        for dk in _DATE_LABELS:
            if dk in kv_nodes:
                m = _DATE.search(kv_nodes[dk].text())
                if m:
                    posted = m.group(0)
                    break
        if posted is None:  # fallback: any date in the header table (not the body)
            m = _DATE.search(v.text())
            posted = m.group(0) if m else None
        if "조회수" in kv_nodes:
            views = _norm(kv_nodes["조회수"].text())
        # Only take the dedicated content node. NEVER fall back to `v` (the whole
        # header table) or a page container — that yields shared template chrome.
        body = _clean_text(tree.css_first(".context"))
    else:
        # gallery/webzine template
        gt = tree.css_first(".gal-tit")
        title = _norm(gt.text()) if gt and _norm(gt.text()) else ""
        # Dedicated content nodes only. No div.subContent / whole-page fallback:
        # gallery detail pages share one subContent wrapper (CSS + search UI),
        # so falling back there gave every post an identical bogus body.
        body = _clean_text(tree.css_first(".cont_txt") or tree.css_first(".cont_sub"))
    if not title:
        title = list_title  # list row is authoritative when detail omits title
    atts = extract_attachments(html)
    doc = Document(unit_type, title=title, body_text=body, posted_at=posted,
                   meta={"views": views}, attachments=atts)
    doc.content_hash = _hash(body or title, atts)
    return doc


def _table_kv(table) -> dict:
    """Pair th->td within each row (handles rows with multiple th/td pairs)."""
    kv: dict = {}
    for tr in table.css("tr"):
        cells = tr.css("th, td")
        i = 0
        while i < len(cells) - 1:
            if cells[i].tag == "th" and cells[i + 1].tag == "td":
                label = _norm(cells[i].text())
                if label and label not in kv:
                    kv[label] = _norm(cells[i + 1].text())
                i += 2
            else:
                i += 1
    return kv


def extract_research_detail(html: str) -> Document:
    tree = HTMLParser(html)
    meta: dict = {}
    # pick the metadata table that actually describes the report (has 제목)
    for table in tree.css("table"):
        if "제목" in table.text():
            kv = _table_kv(table)
            if "제목" in kv:
                meta = kv
                break
    title = meta.get("제목", "")
    posted = meta.get("발행연도") or meta.get("발행년도")
    body = meta.get("초록") or meta.get("영문초록") or ""
    atts = extract_attachments(html)
    doc = Document("research", title=title, body_text=body or title,
                   posted_at=posted, meta=meta, attachments=atts)
    doc.content_hash = _hash(body or title, atts)
    return doc


def extract_static_detail(html: str) -> Document:
    tree = HTMLParser(html)
    root = tree.css_first("div.subContent") or tree.css_first("#container")
    title = ""
    for sel in ("h2.h2_title", "h3.h3_title", "h4.h4_title"):
        el = tree.css_first(sel)
        if el and _norm(el.text()):
            title = _norm(el.text())
            break
    body = _clean_text(root)
    atts = extract_attachments(html)
    doc = Document("static", title=title, body_text=body, attachments=atts)
    doc.content_hash = _hash(body, atts)
    return doc


DETAIL_EXTRACTORS = {
    "board": extract_board_detail,
    "research": extract_research_detail,
    "pub": extract_research_detail,
    "static": extract_static_detail,
}


def extract_detail(unit_type: str, html: str) -> Document:
    fn = DETAIL_EXTRACTORS.get(unit_type)
    if not fn:
        # generic fallback for bid/voc
        tree = HTMLParser(html)
        body = _clean_text(tree.css_first("#container") or tree.body)
        atts = extract_attachments(html)
        d = Document(unit_type, body_text=body, attachments=atts)
        d.content_hash = _hash(body, atts)
        return d
    return fn(html)
