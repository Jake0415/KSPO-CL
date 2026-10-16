"""브라우저 하베스터 — 세션/JS 게이트 공개 게시판(sqms·spowell 등)의 상세를 수집.

일반 크롤(goto)로는 못 잡는 두 부류의 공개 게시판을 Playwright로 수집한다:
  - CLICK 모드(sqms): 목록은 열리지만 상세는 세션/JS라, 목록에서 행을 '클릭'해야 본문이
    렌더된다. 상세 URL 직접 goto는 빈 셸.
  - GOTO 모드(spowell): 목록이 AJAX(_csrf)로 막혀 브라우저 렌더가 필요하지만, 상세는
    GET으로 서버 렌더된다. 목록에서 글 ID만 뽑아 상세 URL로 goto.

공통: 목록 행에서 글 ID(fn_view('X')/fnViewBbs('X')/BRD_CON_SN=X)와 날짜를 뽑고,
상세 본문(content_selectors) + 첨부파일명을 추출해 SONAR에 upsert+scrape.

정책: 게시일 있으면 board_freshness_days(90일=3개월) 이내만, 없으면 전부.
source는 상세 URL(고유 ID 포함) → 재실행 멱등. 로그인/NetFunnel 게이트(spobiz·edu·
nfa, /mypage/*)는 회원 전용이라 대상 아님.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from kspo_ingest.observability.logger import get_logger
from kspo_ingest.settings import settings
from kspo_ingest.sonar.kb_index import purge_kb_points

log = get_logger("worker", "browser_harvest")

# 하베스트 대상(공개 세션-게이트 게시판).
#   row_selector    : 목록 행 셀렉터(기본 "table tr").
#   detail_url_tmpl : 있으면 GOTO 모드(상세 URL로 이동). 없으면 CLICK 모드(행 클릭).
#   content_selectors: 상세 본문 컨테이너 후보(앞에서부터 매칭).
#   tags            : 추가 태그.
_SQMS = "sqms.kspo.or.kr"
_SPW = "spowell.kspo.or.kr"
HARVEST_TARGETS: list[dict] = [
    # sqms — CLICK 모드, 본문 div.basic, 행 fn_view('ID').
    {"host": _SQMS, "list_url": "https://sqms.kspo.or.kr/info/noticeList.kspo", "tags": ["k:공지"]},
    {"host": _SQMS, "list_url": "https://sqms.kspo.or.kr/info/dispoList.kspo", "tags": ["k:행정처분"]},
    {"host": _SQMS, "list_url": "https://sqms.kspo.or.kr/exam/wrQnaList.kspo",
     "tags": ["k:필기시험", "k:정답"]},
    {"host": _SQMS, "list_url": "https://sqms.kspo.or.kr/support/dataList.kspo", "tags": ["k:자료실"]},
    # sqms 단일 안내 페이지(목록 아님) — 페이지 전체를 1문서로. 수수료표가 여러 카드로 분산.
    {"host": _SQMS, "list_url": "https://sqms.kspo.or.kr/info/commisionInfo.kspo", "single_page": True,
     "title": "체육지도자 자격검정 응시수수료 안내", "content_selectors": ["div.cptTable", "div.basic"],
     "tags": ["k:응시수수료", "k:시험안내"]},
    {"host": _SQMS, "list_url": "https://sqms.kspo.or.kr/info/schedPlan.kspo", "single_page": True,
     "title": "체육지도자 자격검정 및 연수 일정", "content_selectors": ["div.cptTable", "div.basic"],
     "tags": ["k:시험일정", "k:시험안내"]},
    {"host": _SQMS, "list_url": "https://sqms.kspo.or.kr/info/licenseInfo.kspo", "single_page": True,
     "title": "체육지도자 자격 종목·자격증 안내", "content_selectors": ["div.cptTable", "div.basic"],
     "tags": ["k:자격안내", "k:시험안내"]},
    {"host": _SQMS, "list_url": "https://sqms.kspo.or.kr/info/licenseInfoPsc1.kspo", "single_page": True,
     "title": "장애인스포츠지도사 자격 안내", "content_selectors": ["div.cptTable", "div.basic"],
     "tags": ["k:자격안내", "k:장애인스포츠지도사"]},
    {"host": _SQMS, "list_url": "https://sqms.kspo.or.kr/info/examOrgInfo.kspo", "single_page": True,
     "title": "체육지도자 자격검정 시행기관 안내", "content_selectors": ["div.cptTable", "div.basic"],
     "tags": ["k:시험기관", "k:시험안내"]},
    {"host": _SQMS, "list_url": "https://sqms.kspo.or.kr/info/gradeOrgInfo.kspo", "single_page": True,
     "title": "체육지도자 자격검정 채점기관 안내", "content_selectors": ["div.cptTable", "div.basic"],
     "tags": ["k:채점기관", "k:시험안내"]},
    {"host": _SQMS, "list_url": "https://sqms.kspo.or.kr/info/saOrgInfoList.kspo", "single_page": True,
     "title": "체육지도자 연수기관 안내", "content_selectors": ["div.cptTable", "div.basic"],
     "tags": ["k:연수기관", "k:시험안내"]},
    # spowell — GOTO 모드, 목록 브라우저 렌더(li), 상세 GET, 본문 .cptBoardDetail.
    {"host": _SPW, "list_url": "https://spowell.kspo.or.kr/bbs/notice?mSn=7394",
     "row_selector": "li", "detail_url_tmpl": "https://spowell.kspo.or.kr/bbs/notice/{sn}?mSn=7394",
     "content_selectors": [".cptBoardDetail", ".detailCont"], "tags": ["k:공지", "k:체육인복지"]},
    {"host": _SPW, "list_url": "https://spowell.kspo.or.kr/bbs/welfare?mSn=7395",
     "row_selector": "li", "detail_url_tmpl": "https://spowell.kspo.or.kr/bbs/welfare/{sn}?mSn=7395",
     "content_selectors": [".cptBoardDetail", ".detailCont"], "tags": ["k:복지신청", "k:체육인복지"]},
    {"host": _SPW, "list_url": "https://spowell.kspo.or.kr/bbs/promising?mSn=7663",
     "row_selector": "li", "detail_url_tmpl": "https://spowell.kspo.or.kr/bbs/promising/{sn}?mSn=7663",
     "content_selectors": [".cptBoardDetail", ".detailCont"], "tags": ["k:스포츠꿈나무"]},
    {"host": _SPW, "list_url": "https://spowell.kspo.or.kr/bbs/news?mSn=7396",
     "row_selector": "li", "detail_url_tmpl": "https://spowell.kspo.or.kr/bbs/news/{sn}?mSn=7396",
     "content_selectors": [".cptBoardDetail", ".detailCont"], "tags": ["k:보도자료"]},
    {"host": _SPW, "list_url": "https://spowell.kspo.or.kr/bbs/data?mSn=7397",
     "row_selector": "li", "detail_url_tmpl": "https://spowell.kspo.or.kr/bbs/data/{sn}?mSn=7397",
     "content_selectors": [".cptBoardDetail", ".detailCont"], "tags": ["k:자료실"]},
]
_DEFAULT_SELECTORS = ["div.basic", "div.view", "div.board_view", "div.cont", "td.cont"]
_BASE_TAGS = ["kspo", "ingest"]

_DATE_RE = re.compile(r"(20\d\d)[.\-](\d{1,2})[.\-](\d{1,2})")

# 목록 행 열거(row_selector 인자): 날짜 + 글 ID(fn_view/fnViewBbs/BRD_CON_SN)가 있는 행을
# (index, title, date, sn)로 반환.
_ROW_JS = r"""(rowSel) => {
  const out = [];
  document.querySelectorAll(rowSel).forEach((el, i) => {
    const txt = (el.innerText || '').replace(/\s+/g, ' ').trim();
    const dm = txt.match(/20\d\d[.\-]\d\d?[.\-]\d\d?/);
    if (!dm) return;
    const sm = (el.innerHTML || '').match(/(?:BRD_CON_SN[=,'"\s]*|\bfn\w*\(\s*['"]?)(\d{2,})/);
    if (!sm) return;
    const a = el.querySelector('a, p.title, [onclick]');
    out.push({ i, title: ((a ? a.innerText : txt) || '').trim(), date: dm[0], sn: sm[1] });
  });
  return out;
}"""

# 상세에서 본문(후보 셀렉터 중 첫 매칭) + 첨부파일명 추출.
_EXTRACT_JS = r"""(selectors) => {
  let body = '';
  for (const sel of selectors) {
    const c = document.querySelector(sel);
    if (c && c.innerText.trim().length > 25) { body = c.innerText.trim(); break; }
  }
  const dls = [];
  document.querySelectorAll('a[onclick*=fnDownloadFile], a[href*=fnDownloadFile], a[onclick*=download]')
    .forEach(x => { const t = (x.innerText || '').trim(); if (t) dls.push(t); });
  return { body, downloads: dls.slice(0, 8) };
}"""


# 단일 페이지: 각 셀렉터에 매칭되는 '모든' 요소의 텍스트를 합쳐 반환(수수료표가 여러
# 카드로 분산된 경우 대비). 첫 번째로 내용이 잡히는 셀렉터를 사용.
_SINGLE_EXTRACT_JS = r"""(selectors) => {
  for (const sel of selectors) {
    const els = document.querySelectorAll(sel);
    if (!els.length) continue;
    const txt = [...els].map(e => e.innerText.trim()).filter(Boolean).join('\n');
    if (txt.length > 40) return txt;
  }
  return '';
}"""


def _parse_date(s: str | None) -> datetime | None:
    m = _DATE_RE.search(s or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC)
    except ValueError:
        return None


def _view_url(list_url: str, sn: str) -> str:
    """CLICK 모드 source: 목록 URL(*List.kspo)을 상세 URL(*View.kspo?BRD_CON_SN=sn)로 변환."""
    base = list_url.split("?", 1)[0]
    view = re.sub(r"List\.kspo$", "View.kspo", base)
    return f"{view}?BRD_CON_SN={sn}"


async def _harvest_single_page(browser, t: dict, sonar, ns: str, selectors, tags) -> int:
    """단일 안내 페이지(응시수수료 등) 1건을 수집. 세션 확보 위해 홈 먼저 방문."""
    pg = await browser.new_page()
    try:
        await pg.goto(f"https://{t['host']}/", wait_until="networkidle", timeout=40000)
        await pg.wait_for_timeout(1000)
        await pg.goto(t["list_url"], wait_until="networkidle", timeout=30000)
        await pg.wait_for_timeout(2000)
        body = (await pg.evaluate(_SINGLE_EXTRACT_JS, selectors)).strip()
        if len(body) < 40:
            return 0
        title = t.get("title") or (await pg.title())
        content = f"{title}\n\n{body}"
        res = await sonar.upsert_kb(
            name=title[:200], content=content, source=t["list_url"], namespace=ns, tags=tags,
        )
        kb_id = (res.get("value") or {}).get("_id")
        if kb_id:
            await purge_kb_points(kb_id)  # 재색인 멱등성(중복 방지)
            await sonar.trigger_scrape_single(kb_id=kb_id, namespace=ns, kb_type="text")
        return 1
    finally:
        await pg.close()


async def browser_harvest(ctx: dict) -> dict:
    """세션-게이트 게시판 하베스트 크론. 반환: {list_url: 적재수}."""
    sonar = ctx.get("sonar_client")
    if sonar is None:
        log.bind(event="harvest_no_sonar").info("SONAR 미설정 — skip")
        return {}
    ns = ctx.get("sonar_namespace") or settings.sonar_project_id

    from playwright.async_api import async_playwright  # 지연 import

    now = datetime.now(UTC)
    result: dict[str, int] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            for t in HARVEST_TARGETS:
                key = t["list_url"]
                try:
                    result[key] = await _harvest_board(browser, t, sonar, ns, now)
                except Exception as exc:
                    log.bind(event="harvest_board_error", list_url=key, err=str(exc)[:200]).warning(
                        "board harvest failed"
                    )
                    result[key] = 0
        finally:
            await browser.close()
    log.bind(event="browser_harvest_done", result=result).info("harvest complete")
    return result


async def _harvest_board(browser, t: dict, sonar, ns: str, now: datetime) -> int:
    cutoff = now - timedelta(days=settings.board_freshness_days)
    selectors = t.get("content_selectors") or _DEFAULT_SELECTORS
    row_sel = t.get("row_selector") or "table tr"
    detail_tmpl = t.get("detail_url_tmpl")  # 있으면 GOTO 모드
    tags = _BASE_TAGS + [f"d:{t['host']}"] + list(t.get("tags") or [])
    if t.get("single_page"):  # 단일 안내 페이지(목록 없음): 페이지 자체를 1문서로 수집.
        return await _harvest_single_page(browser, t, sonar, ns, selectors, tags)
    pg = await browser.new_page()
    try:
        await pg.goto(t["list_url"], wait_until="networkidle", timeout=40000)
        await pg.wait_for_timeout(2500)
        rows = await pg.evaluate(_ROW_JS, row_sel)
        # 날짜 있으면 최근만, 없으면 전부. SN 없는 행은 이미 _ROW_JS에서 제외됨.
        targets = [r for r in rows if (_parse_date(r.get("date")) or now) >= cutoff]

        pushed = 0
        for r in targets:
            try:
                if detail_tmpl:  # GOTO 모드(spowell): 상세 URL 직접 이동.
                    source = detail_tmpl.format(sn=r["sn"])
                    await pg.goto(source, wait_until="networkidle", timeout=30000)
                    await pg.wait_for_timeout(1200)
                else:  # CLICK 모드(sqms): 목록 재로드 후 행 클릭.
                    await pg.goto(t["list_url"], wait_until="networkidle", timeout=40000)
                    await pg.wait_for_timeout(700)
                    await pg.locator(row_sel).nth(r["i"]).locator("a, [onclick]").first.click(timeout=8000)
                    await pg.wait_for_load_state("networkidle", timeout=20000)
                    await pg.wait_for_timeout(2000)
                    source = _view_url(t["list_url"], r["sn"])

                data = await pg.evaluate(_EXTRACT_JS, selectors)
                body = (data.get("body") or "").strip()
                downloads = data.get("downloads") or []
                if len(body) < 25 and not downloads:
                    continue
                parts = [r["title"], body]
                if downloads:
                    parts.append("첨부파일: " + ", ".join(downloads))
                content = "\n\n".join(x for x in parts if x)
                res = await sonar.upsert_kb(
                    name=r["title"][:200], content=content, source=source, namespace=ns, tags=tags,
                )
                kb_id = (res.get("value") or {}).get("_id")
                if kb_id:
                    await purge_kb_points(kb_id)  # 재색인 멱등성(중복 방지)
                    await sonar.trigger_scrape_single(kb_id=kb_id, namespace=ns, kb_type="text")
                pushed += 1
            except Exception as exc:
                log.bind(event="harvest_item_error", list_url=t["list_url"], err=str(exc)[:150]).warning(
                    "item harvest failed"
                )
        return pushed
    finally:
        await pg.close()
