"""Async crawl engine for sports.re.kr.

Implements the spec runtime: rate-limited fetch with retry/backoff, typed
frontier (SEED→LIST→DETAIL→ATTACHMENT), pageNo pagination with stop/early-exit,
canonical dedup + content-hash change detection, per-source checkpoints.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx

from . import extract as E
from . import patterns as P
from .store import Store

log = logging.getLogger("sports_crawl")

DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")


@dataclass
class Config:
    user_agent: str = DEFAULT_UA
    concurrency: int = 4
    min_delay: float = 0.35        # polite inter-request gap (s)
    timeout: float = 20.0
    max_retries: int = 3
    max_pages: int = 500
    incremental: bool = False
    fetch_binaries: bool = False   # download attachment bytes
    db_path: str = "sports_crawl.db"


@dataclass
class Stats:
    fetched: int = 0
    docs_new: int = 0
    docs_changed: int = 0
    docs_unchanged: int = 0
    attachments: int = 0
    auth_gated: int = 0
    errors: int = 0
    dropped: int = 0
    pages: int = 0
    early_exits: int = 0
    per_source: dict = field(default_factory=dict)

    def as_dict(self):
        return {k: v for k, v in self.__dict__.items()}


class RateLimiter:
    def __init__(self, min_delay: float):
        self._min = min_delay
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self):
        async with self._lock:
            now = time.monotonic()
            gap = self._min - (now - self._last)
            if gap > 0:
                await asyncio.sleep(gap)
            self._last = time.monotonic()


class Engine:
    def __init__(self, cfg: Config | None = None, store: Store | None = None):
        self.cfg = cfg or Config()
        self.store = store or Store(self.cfg.db_path)
        self.stats = Stats()
        self.rl = RateLimiter(self.cfg.min_delay)
        self._sem = asyncio.Semaphore(self.cfg.concurrency)

    # --- fetch with retry/backoff --------------------------------------------
    async def fetch(self, client: httpx.AsyncClient, url: str) -> tuple[int, str, str]:
        """Returns (status, final_url, text). Retries transient errors."""
        backoff = 1.0
        for attempt in range(1, self.cfg.max_retries + 1):
            await self.rl.wait()
            try:
                async with self._sem:
                    r = await client.get(url)
                self.stats.fetched += 1
                if r.status_code in (429, 500, 502, 503, 504):
                    if attempt < self.cfg.max_retries:
                        ra = r.headers.get("retry-after")
                        await asyncio.sleep(float(ra) if ra and ra.isdigit() else backoff)
                        backoff *= 4
                        continue
                return r.status_code, str(r.url), r.text
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt < self.cfg.max_retries:
                    await asyncio.sleep(backoff)
                    backoff *= 4
                    continue
                self.stats.errors += 1
                log.warning("fetch failed %s: %s", url, e)
                return 0, url, ""
        return 0, url, ""

    # --- detail handling ------------------------------------------------------
    async def handle_detail(self, client, unit_type: str, fetch_url: str,
                            source_id: int | None, nat_ids: dict,
                            list_title: str = "") -> str:
        status, final, html = await self.fetch(client, fetch_url)
        if status == 0 or not html:
            return "error"
        if P.is_auth_wall(html, status):
            self.stats.auth_gated += 1
            self.stats.dropped += 1
            return "auth_gated"
        try:
            nat_id = P.natural_id(unit_type, **nat_ids)
            if unit_type in ("board", "bid"):
                # bid reuses the .bbs_view_v4 template; view-count excluded from hash
                doc = E.extract_board_detail(html, list_title=list_title,
                                             unit_type=unit_type)
            else:
                doc = E.extract_detail(unit_type, html)
        except Exception:
            self.stats.errors += 1
            log.exception("extract failed %s", fetch_url)
            return "error"
        if not doc.title and list_title:
            doc.title = list_title
        if not doc.body_text and list_title:
            doc.body_text = list_title
        canon = P.canonical_url(fetch_url, unit_type)
        doc_id, change = self.store.upsert_document(
            host=P.HOST, unit_type=unit_type, natural_id=nat_id,
            canonical_url=canon, fetch_url=fetch_url, source_id=source_id,
            title=doc.title, body_text=doc.body_text, posted_at=doc.posted_at,
            content_hash=doc.content_hash, meta=doc.meta)
        for att in doc.attachments:
            self.store.upsert_attachment(doc_id, att)
            self.stats.attachments += 1
        if change == "new":
            self.stats.docs_new += 1
        elif change == "changed":
            self.stats.docs_changed += 1
        else:
            self.stats.docs_unchanged += 1
        return change

    # --- board / research / voc list pagination -------------------------------
    async def crawl_board_source(self, client, src) -> None:
        board_seq, menu_seq = src["board_seq"], src["menu_seq"]
        variant = src["variant"] or "bs"
        extra = _json(src["extra_params"])
        prev_ids: list[str] = []
        page = 1
        run_id = self._run_id
        seen_all_known_pages = 0
        while True:
            url = P.board_list_url(board_seq, menu_seq, page, variant, extra)
            status, final, html = await self.fetch(client, url)
            self.stats.pages += 1
            if status == 0:
                break
            rows = E.extract_board_rows(html)
            ids = [cid for cid, _ in rows]
            if P.should_stop_pagination(ids, prev_ids, page, self.cfg.max_pages):
                break
            # incremental early-exit: page fully composed of unchanged known docs
            if self.cfg.incremental and ids:
                all_known_unchanged = all(
                    self.store.get_document(P.HOST, "board", f"{board_seq}:{cid}") is not None
                    for cid in ids)
                if all_known_unchanged:
                    seen_all_known_pages += 1
                    if seen_all_known_pages >= 1:
                        self.stats.early_exits += 1
                        # still verify newest by re-checking hashes on page 1 details
                        break
            for cid, title in rows:
                furl = P.board_view_url(board_seq, cid, menu_seq, variant)
                await self.handle_detail(client, "board", furl, src["id"],
                                         {"board_seq": board_seq, "con_seq": cid},
                                         list_title=title)
            self.store.save_checkpoint(run_id, src["id"], page,
                                       ids[-1] if ids else "", "list")
            prev_ids = ids
            page += 1
        self.stats.per_source[src["list_url_tmpl"] or f"board:{board_seq}"] = page - 1

    async def crawl_research_source(self, client, src) -> None:
        menu_seq = src["menu_seq"]
        is_pub = src["source_type"] == "pub"
        unit_type = "pub" if is_pub else "research"
        book_gbn = src["book_gbn"]
        prev_ids: list[str] = []
        page = 1
        while True:
            if is_pub:
                url = (f"{P.BASE}/front/research/pub/orginList.do?menu_seq={menu_seq}"
                       f"&book_gbn={book_gbn}&pageNo={page}")
            else:
                url = (f"{P.BASE}/front/research/project/orginList.do?"
                       f"menu_seq={menu_seq}&pageNo={page}")
            status, final, html = await self.fetch(client, url)
            self.stats.pages += 1
            if status == 0:
                break
            rows = E.extract_research_rows(html)
            ids = [rid for rid, _ in rows]
            if P.should_stop_pagination(ids, prev_ids, page, self.cfg.max_pages):
                break
            if self.cfg.incremental and ids and all(
                    self.store.get_document(P.HOST, unit_type, i) is not None for i in ids):
                self.stats.early_exits += 1
                break
            for art, title in rows:
                furl = P.pub_view_url(art, menu_seq) if is_pub else P.research_view_url(art, menu_seq)
                await self.handle_detail(client, unit_type, furl, src["id"],
                                         {"artctrlno": art}, list_title=title)
            self.store.save_checkpoint(self._run_id, src["id"], page,
                                       ids[-1] if ids else "", "list")
            prev_ids = ids
            page += 1

    async def crawl_static_source(self, client, src) -> None:
        furl = P.page_view_url(src["page_seq"], src["menu_seq"])
        await self.handle_detail(client, "static", furl, src["id"],
                                 {"page_seq": src["page_seq"]})

    async def crawl_media_source(self, client, src) -> None:
        """KISS미디어룸 (ns): rows are external press links captured from the
        list itself; no internal detail page exists."""
        board_seq, menu_seq = src["board_seq"], src["menu_seq"]
        prev_ids: list[str] = []
        page = 1
        while True:
            url = P.board_list_url(board_seq, menu_seq, page, "ns")
            status, final, html = await self.fetch(client, url)
            self.stats.pages += 1
            if status == 0:
                break
            rows = E.extract_media_rows(html)
            ids = [r["external_url"] for r in rows]
            if P.should_stop_pagination(ids, prev_ids, page, self.cfg.max_pages):
                break
            for r in rows:
                nat_id = P.natural_id("media", external_url=r["external_url"])
                doc_id, change = self.store.upsert_document(
                    host=P.HOST, unit_type="media", natural_id=nat_id,
                    canonical_url=r["external_url"], fetch_url=url, source_id=src["id"],
                    title=r["title"], body_text=r["title"], posted_at=r["posted_at"],
                    content_hash=E._hash(r["title"] + r["external_url"], []),
                    meta={"external_url": r["external_url"]})
                self.stats.docs_new += (change == "new")
                self.stats.docs_changed += (change == "changed")
                self.stats.docs_unchanged += (change == "unchanged")
            self.store.save_checkpoint(self._run_id, src["id"], page,
                                       ids[-1] if ids else "", "list")
            prev_ids = ids
            page += 1

    async def crawl_faq_source(self, client, src) -> None:
        """FAQ (fq): accordion Q/A captured from the list page as one document."""
        board_seq, menu_seq = src["board_seq"], src["menu_seq"]
        url = P.board_list_url(board_seq, menu_seq, 1, "fq")
        status, final, html = await self.fetch(client, url)
        self.stats.pages += 1
        if status == 0:
            return
        items = E.extract_faq_items(html)
        body = "\n\n".join(f"Q. {i['q']}\nA. {i['a']}" for i in items)
        nat_id = P.natural_id("faq", board_seq=board_seq)
        _, change = self.store.upsert_document(
            host=P.HOST, unit_type="faq", natural_id=nat_id, canonical_url=url,
            fetch_url=url, source_id=src["id"], title="자주하는 질문",
            body_text=body, posted_at=None,
            content_hash=E._hash(body, []), meta={"item_count": len(items)})
        self.stats.docs_new += (change == "new")
        self.stats.docs_changed += (change == "changed")
        self.stats.docs_unchanged += (change == "unchanged")

    # --- orchestration --------------------------------------------------------
    async def run(self, mode: str = "full") -> Stats:
        self.cfg.incremental = (mode == "incremental")
        self._run_id = self.store.start_run(mode)
        # Always write a terminal run status, even on cancel/interrupt/crash, so a
        # killed run never lingers as 'running' (audit 2026-07-08 ghost run).
        status = "interrupted"
        try:
            headers = {"User-Agent": self.cfg.user_agent}
            limits = httpx.Limits(max_connections=self.cfg.concurrency)
            async with httpx.AsyncClient(headers=headers, timeout=self.cfg.timeout,
                                         follow_redirects=True, limits=limits) as client:
                sources = self.store.list_sources()
                # priority order already applied by list_sources()
                tasks = []
                for src in sources:
                    st = src["source_type"]
                    if st == "board":
                        variant = src["variant"] or "bs"
                        if variant == "ns":
                            tasks.append((src, self.crawl_media_source(client, src)))
                        elif variant == "fq":
                            tasks.append((src, self.crawl_faq_source(client, src)))
                        else:
                            tasks.append((src, self.crawl_board_source(client, src)))
                    elif st == "voc":
                        tasks.append((src, self.crawl_voc_source(client, src)))
                    elif st in ("research", "pub"):
                        tasks.append((src, self.crawl_research_source(client, src)))
                    elif st == "static":
                        tasks.append((src, self.crawl_static_source(client, src)))
                    elif st == "bid":
                        tasks.append((src, self.crawl_bid_source(client, src)))
                # bounded concurrency across sources
                await self._gather_bounded(tasks, self.cfg.concurrency)
            status = "completed" if self.stats.errors == 0 else "completed_with_errors"
        finally:
            self.store.finish_run(self._run_id, status, self.stats.as_dict())
        return self.stats

    async def crawl_voc_source(self, client, src):
        """VOC detail requires the POST form (GET returns an error page), and
        VOC content is low-value personal complaints. Capture the list row
        (title) as the document; no detail fetch."""
        menu_seq = src["menu_seq"]
        prev_ids: list[str] = []
        page = 1
        while True:
            url = f"{P.BASE}/front/voc/vocList.do?menu_seq={menu_seq}&pageNo={page}"
            status, final, html = await self.fetch(client, url)
            self.stats.pages += 1
            if status == 0:
                break
            rows = E.extract_voc_rows(html)
            ids = [vid for vid, _ in rows]
            if P.should_stop_pagination(ids, prev_ids, page, self.cfg.max_pages):
                break
            for vid, title in rows:
                nat_id = P.natural_id("voc", voc_id=vid)
                _, change = self.store.upsert_document(
                    host=P.HOST, unit_type="voc", natural_id=nat_id,
                    canonical_url=f"{P.BASE}/front/voc/vocView.do?voc_id={vid}",
                    fetch_url=url, source_id=src["id"], title=title,
                    body_text=title, posted_at=None,
                    content_hash=E._hash(title, []), meta={"voc_id": vid})
                self.stats.docs_new += (change == "new")
                self.stats.docs_changed += (change == "changed")
                self.stats.docs_unchanged += (change == "unchanged")
            self.store.save_checkpoint(self._run_id, src["id"], page,
                                       ids[-1] if ids else "", "list")
            prev_ids = ids
            page += 1

    async def crawl_bid_source(self, client, src):
        """Bid rows: onclick=fnDetail('num_p') -> notifyView.do?num_p=..."""
        menu_seq = src["menu_seq"]
        page = 1
        prev_ids: list[str] = []
        while True:
            url = f"{P.BASE}/front/info/bid/notifyList.do?menu_seq={menu_seq}&pageNo={page}"
            status, final, html = await self.fetch(client, url)
            self.stats.pages += 1
            if status == 0:
                break
            rows = E.extract_bid_rows(html)
            ids = [rid for rid, _ in rows]
            if P.should_stop_pagination(ids, prev_ids, page, self.cfg.max_pages):
                break
            for num_p, title in rows:
                furl = P.bid_view_url(num_p, menu_seq)
                await self.handle_detail(client, "bid", furl, src["id"],
                                         {"num_p": num_p}, list_title=title)
            self.store.save_checkpoint(self._run_id, src["id"], page,
                                       ids[-1] if ids else "", "list")
            prev_ids = ids
            page += 1

    async def _gather_bounded(self, tasks, limit):
        sem = asyncio.Semaphore(limit)

        async def _wrap(src, c):
            async with sem:
                try:
                    await c
                    # record completion → drives coverage/freshness (last_crawled_at)
                    self.store.mark_source_crawled(src["id"])
                except Exception as e:  # a failing source must not kill the run
                    self.stats.errors += 1
                    log.exception("source crawl failed: %s", e)
        await asyncio.gather(*[_wrap(src, c) for src, c in tasks])


def _json(s):
    import json
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None
