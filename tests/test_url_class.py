"""Generalized non-content URL classification (engine rule, 2026-07-11)."""
from __future__ import annotations

import pytest

from kspo_ingest.crawl.url_class import is_non_content_url

# Reported defects + variants that MUST be classified non-content.
NON_CONTENT = [
    "https://spobiz.kspo.or.kr/job/front/job/user/pw_search.do?user_kind=1",  # spobiz
    "https://spowell.kspo.or.kr/member/find-id",                              # spowell
    "https://x.kspo.or.kr/login/login.do",
    "https://x.kspo.or.kr/member/join.do",
    "https://x.kspo.or.kr/mypage/index.do",
    "https://x.kspo.or.kr/user/findId.do",
    "https://x.kspo.or.kr/user/find_pw.kspo",
    "https://x.kspo.or.kr/login/findVoucherInfo.do",
    "https://x.kspo.or.kr/cert/checkplusopen.do",
    "https://x.kspo.or.kr/logout",
    "/member/memberWithdraw.do",
    "/order/cart",
]

# Real content that must NOT be dropped (false-positive guards).
CONTENT = [
    "https://svoucher.kspo.or.kr/voucher/voucherSelectArea.do",
    "https://www.kspo.or.kr/kspo/bbs/B0000019/list.do?menuNo=200073",
    "https://www.ksponco.or.kr/board.es?bid=0067&mid=a10309000000",
    "https://www.sports.re.kr/front/board/ga/boardView.do?con_seq=1376",
    "https://x.kspo.or.kr/reorder/recorder.do",   # 'order' substring, not a segment
    "https://x.kspo.or.kr/concert/certificate.do",  # 'cert' substring
    "https://x.kspo.or.kr/border/blueprint.do",     # 'order'/'print' substrings
    "https://x.kspo.or.kr/business/support.do",
]


@pytest.mark.parametrize("url", NON_CONTENT)
def test_non_content_detected(url):
    assert is_non_content_url(url) is True, url


@pytest.mark.parametrize("url", CONTENT)
def test_content_not_flagged(url):
    assert is_non_content_url(url) is False, url


def test_discover_excludes_auth_links():
    from kspo_ingest.crawl.internal_links import discover_internal_links
    html = """
      <a href="/member/find-id">아이디찾기</a>
      <a href="/job/user/pw_search.do?user_kind=1">비밀번호찾기</a>
      <a href="/login/login.do">로그인</a>
      <a href="/business/support.do">사업소개</a>
    """
    urls = discover_internal_links(html, base_url="https://spobiz.kspo.or.kr/",
                                   host="spobiz.kspo.or.kr")
    assert any("support.do" in u for u in urls)
    assert not any("find-id" in u or "pw_search" in u or "login" in u for u in urls)


def test_download_export_endpoints_are_non_content():
    from kspo_ingest.crawl.url_class import is_non_content_url
    for u in [
        "/kspo/cmmn/file/fileDown.do?atchFileId=abc",
        "/kspo/fund/expenditureManagement/dwndExcel.do?menuNo=200254",
        "/kspo/board/downExcel.do",
        "/kspo/x/excelDown.do?id=1",
        "/kspo/x/fileDownload.do",
    ]:
        assert is_non_content_url(u), u


def test_content_pages_not_flagged_as_download():
    from kspo_ingest.crawl.url_class import is_non_content_url
    for u in [
        "/kspo/main/contents.do?menuNo=200207",     # 찾아오시는길
        "/news/bbs/B0000095/view.do?nttId=1",
        "/kspo/singl/bid/list.do?menuNo=200179",
    ]:
        assert not is_non_content_url(u), u
