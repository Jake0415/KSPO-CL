"""Bounded content readiness, separate from global network-idle."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ReadinessPolicy:
    initial_timeout_ms: int = 15000
    action_timeout_ms: int = 5000
    stable_ms: int = 800
    poll_ms: int = 150
    load_timeout_ms: int = 2000
    content_selector: str = "body"
    loading_selector: str = '[aria-busy="true"], .loading-overlay, .loading-mask'

    def __post_init__(self):
        if min(self.initial_timeout_ms, self.action_timeout_ms, self.stable_ms, self.poll_ms) <= 0:
            raise ValueError("Readiness durations must be positive")
        if self.stable_ms >= min(self.initial_timeout_ms, self.action_timeout_ms):
            raise ValueError("Stability window must fit within readiness deadlines")


class ContentReadinessError(RuntimeError):
    pass


_SNAPSHOT = """(selectors) => {
 const node=document.querySelector(selectors.content);
 const visible=el => { const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
   return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden'; };
 const text=(node?.innerText||'').replace(/\\s+/g,' ').trim();
 let hash=2166136261;
 for(let i=0;i<text.length;i++) hash=Math.imul(hash^text.charCodeAt(i),16777619);
 return {url:location.href, document_id:performance.timeOrigin,
   ready_state:document.readyState, text_length:text.length, fingerprint:String(hash),
   loading:Array.from(document.querySelectorAll(selectors.loading)).some(visible)};
}"""


class ContentWaiter:
    """Observe AJAX before an action; navigation is detected by document identity too."""

    def __init__(self, page, policy: ReadinessPolicy | None = None):
        self.page = page
        self.policy = policy or ReadinessPolicy()
        self.pending: set[int] = set()
        self.host = urlsplit(page.url).hostname
        self._handlers = [
            ("request", self._request),
            ("requestfinished", self._finished),
            ("requestfailed", self._finished),
        ]

    def start(self):
        for event, handler in self._handlers:
            self.page.on(event, handler)
        return self

    def close(self):
        for event, handler in self._handlers:
            self.page.remove_listener(event, handler)

    def _request(self, request):
        p = urlsplit(request.url)
        if (
            request.resource_type in ("xhr", "fetch")
            and p.hostname == self.host
            and not re.search(r"analytics|telemetry|heartbeat|longpoll|/poll(?:/|$)", p.path, re.I)
        ):
            self.pending.add(id(request))

    def _finished(self, request):
        self.pending.discard(id(request))

    async def snapshot(self):
        return await self.page.evaluate(
            _SNAPSHOT,
            {
                "content": self.policy.content_selector,
                "loading": self.policy.loading_selector,
            },
        )

    async def wait(self, *, initial: bool, before: dict | None = None) -> dict:
        policy = self.policy
        deadline = (
            time.monotonic()
            + (policy.initial_timeout_ms if initial else policy.action_timeout_ms) / 1000
        )
        mode = "navigation" if initial else "dynamic"
        load_complete = False
        load_checked = False
        last = None
        stable_since = time.monotonic()
        state = {}
        while time.monotonic() < deadline:
            try:
                remaining = max(0.001, deadline - time.monotonic())
                state = await asyncio.wait_for(self.snapshot(), timeout=min(2.0, remaining))
            except Exception:
                # Execution contexts disappear while redirects replace documents.
                await asyncio.sleep(policy.poll_ms / 1000)
                continue
            if (
                before
                and (state["url"] != before["url"] or state["document_id"] != before["document_id"])
                and mode == "dynamic"
            ):
                mode = "navigation"
                deadline = time.monotonic() + policy.initial_timeout_ms / 1000
            if mode == "navigation" and not load_checked:
                try:
                    remaining = max(0.001, deadline - time.monotonic())
                    load_ms = min(policy.load_timeout_ms, max(1, int(remaining * 1000)))
                    await asyncio.wait_for(
                        self.page.wait_for_load_state("load", timeout=load_ms), timeout=remaining
                    )
                    load_complete = True
                except Exception:
                    pass
                load_checked = True
                # Always sample again after load/redirects before accepting content.
                continue
            signature = (state["url"], state["document_id"], state["fingerprint"])
            usable = (
                state["ready_state"] != "loading"
                and state["text_length"] >= 10
                and not state["loading"]
                and not self.pending
            )
            if not usable or signature != last:
                stable_since = time.monotonic()
                last = signature
            elif (time.monotonic() - stable_since) * 1000 >= policy.stable_ms:
                return {
                    "mode": mode,
                    "ready": True,
                    "final_url": state["url"],
                    "load_complete": load_complete,
                    "text_length": state["text_length"],
                }
            await asyncio.sleep(policy.poll_ms / 1000)
        reason = "pending_ajax" if self.pending else "content_not_stable_or_empty"
        raise ContentReadinessError(
            f"{mode}_readiness_timeout:{reason}:{state.get('url', self.page.url)}"
        )


async def wait_initial_content(page, policy: ReadinessPolicy | None = None) -> dict:
    waiter = ContentWaiter(page, policy).start()
    try:
        return await waiter.wait(initial=True)
    finally:
        waiter.close()
