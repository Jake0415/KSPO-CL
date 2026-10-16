"""Unit tests for the sports.re.kr crawler pure logic + extraction."""
from __future__ import annotations

from kspo_ingest.crawl.sports import patterns as P
from kspo_ingest.crawl.sports import extract as E


# --- URL generation -----------------------------------------------------------
def test_board_view_url_with_and_without_menu():
    u1 = P.board_view_url(50, 6586, menu_seq=583)
    u2 = P.board_view_url(50, 6586)
    assert "boardView.do" in u1 and "con_seq=6586" in u1 and "menu_seq=583" in u1
    assert "menu_seq" not in u2 and "con_seq=6586" in u2


def test_board_list_url_carries_filters():
    u = P.board_list_url(37, 682, page=2, extra={"keyKind3": "101"})
    assert "pageNo=2" in u and "keyKind3=101" in u and "board_seq=37" in u


def test_research_and_page_and_file_urls():
    assert "artctrlno=CR_1" in P.research_view_url("CR_1")
    assert "page_seq=27" in P.page_view_url(27, menu_seq=559)
    fu = P.file_download_url("/upload/x/", "stored.pdf")
    assert "fileDownAct.do" in fu and "file_real_nm=stored.pdf" in fu


# --- canonicalization / identity ---------------------------------------------
def test_canonical_strips_menu_and_page():
    a = P.canonical_url("https://www.sports.re.kr/front/board/bs/boardView.do?board_seq=50&menu_seq=583&con_seq=6586&pageNo=1", "board")
    b = P.canonical_url("https://www.sports.re.kr/front/board/bs/boardView.do?con_seq=6586&board_seq=50&menu_seq=999", "board")
    assert a == b  # same unit via different menu_seq -> identical canonical
    assert "menu_seq" not in a and "pageNo" not in a


def test_canonical_research_drops_bibctrlno():
    a = P.canonical_url("https://www.sports.re.kr/front/research/project/orginView.do?menu_seq=594&artctrlno=CR_9&bibctrlno=CR_9&lib_seq=", "research")
    assert "artctrlno=CR_9" in a and "bibctrlno" not in a and "menu_seq" not in a


def test_natural_id_and_dedup_key():
    assert P.natural_id("board", board_seq=50, con_seq=6586) == "50:6586"
    assert P.natural_id("research", artctrlno="CR_9") == "CR_9"
    assert P.dedup_key("www.sports.re.kr", "board", "50:6586") == "www.sports.re.kr|board|50:6586"


def test_unit_type_for():
    assert P.unit_type_for(".../boardView.do?x") == "board"
    assert P.unit_type_for(".../research/project/orginView.do?x") == "research"
    assert P.unit_type_for(".../pageView.do?x") == "static"
    assert P.unit_type_for(".../boardList.do?x") is None


# --- guards -------------------------------------------------------------------
def test_auth_wall_detection():
    stub = "<html><title>알림</title><script>alert('본인인증후에 사용가능합니다.');window.location.href='/front/nice/checkplus/checkplusOpen.do'</script>"
    assert P.is_auth_wall(stub) is True
    assert P.is_auth_wall("<html><body>real content page</body></html>") is False


# --- pagination ---------------------------------------------------------------
def test_extract_page_numbers_and_stop():
    html = "a fnGoPage('1','') b fnGoPage('2','') fnGoPage('11','')"
    assert P.extract_page_numbers(html) == [1, 2, 11]
    assert P.should_stop_pagination([], ["x"], 1, 500) is True         # empty
    assert P.should_stop_pagination(["a"], ["a"], 3, 500) is True      # repeat
    assert P.should_stop_pagination(["a"], ["b"], 500, 500) is False   # inclusive cap
    assert P.should_stop_pagination(["a"], ["b"], 501, 500) is True    # over cap
    assert P.should_stop_pagination(["a"], ["b"], 2, 500) is False


# --- list row extraction ------------------------------------------------------
def test_extract_board_row_ids():
    html = """<a href="javascript:fnBoardContentView('6586')">t1</a>
              <a href="javascript:fnBoardContentView('6566')">t2</a>
              <a href="javascript:fnBoardContentView('6586')">dup</a>"""
    assert E.extract_board_row_ids(html) == ["6586", "6566"]


def test_extract_voc_ids():
    assert E.extract_voc_ids("fnVocView('VB0000132412')") == ["VB0000132412"]


def test_extract_research_rows_fndetail():
    html = """<a onclick="fnDetail('CR_616184', 'CR_616184', '');" href="javascript:void(0);">체육인 재해 연구</a>
              <a onclick="fnDetail('RR_616189', 'RR_616189', '');" href="javascript:void(0);">국제경기대회</a>"""
    rows = E.extract_research_rows(html)
    assert rows == [("CR_616184", "체육인 재해 연구"), ("RR_616189", "국제경기대회")]


def test_extract_pub_ids_two_letter_prefix():
    html = """<a onclick="fnDetail('PS_616120', 'PS_616120', '');" href="#">간행물</a>"""
    assert E.extract_research_ids(html) == ["PS_616120"]


def test_extract_bid_rows_fndetail_numeric():
    html = """<a href="javascript:void(0);" onclick="fnDetail('12749');">입찰 공고</a>"""
    assert E.extract_bid_rows(html) == [("12749", "입찰 공고")]


def test_extract_media_rows_title_from_cell():
    html = """<table><tbody><tr>
      <td>495</td>
      <td><a href="https://ext.example.com/news/1"><img></a></td>
      <td>도쿄올림픽 관련 기사 제목</td>
      <td>2021-12-21</td></tr></tbody></table>"""
    rows = E.extract_media_rows(html)
    assert rows[0]["external_url"] == "https://ext.example.com/news/1"
    assert rows[0]["title"] == "도쿄올림픽 관련 기사 제목"
    assert rows[0]["posted_at"] == "2021-12-21"


# --- attachment extraction ----------------------------------------------------
def test_extract_attachments_cms_and_pyxis():
    html = ("""<a href="javascript:fnFileDownAction('/upload/site/www/plugin/board/50/202605/','최우수칼럼.pdf','202605221414000010.pdf')">f</a>"""
            """<a href="/pyxis-api/1/digital-files/557ba3d9-2cad-42b9-b995-07e3f8ad0b13">p</a>""")
    atts = E.extract_attachments(html)
    kinds = {a.kind for a in atts}
    assert "cms_file" in kinds and "pyxis_file" in kinds
    cms = [a for a in atts if a.kind == "cms_file"][0]
    assert "fileDownAct.do" in cms.download_url
    assert cms.stored_name == "202605221414000010.pdf"
    assert cms.display_name == "최우수칼럼.pdf"


def test_extract_board_detail_snippet():
    html = """<div class="bbs_view_v4"><table>
      <tr><th>제목</th><td>테스트 공지</td></tr>
      <tr><th>조회수</th><td>348</td></tr>
      <tr><th>등록일</th><td>2026-05-22</td></tr>
      <tr><th>첨부</th><td></td></tr></table></div>
      <div class="context">본문 내용입니다.</div>"""
    doc = E.extract_board_detail(html)
    assert doc.title == "테스트 공지"
    assert doc.posted_at == "2026-05-22"
    assert "본문" in doc.body_text
    assert len(doc.content_hash) == 64


# --- audit-driven regression tests (2026-07-10) -------------------------------
from kspo_ingest.crawl.sports.store import Store  # noqa: E402


# RC1: boilerplate/CSS must never leak into body_text; no whole-page fallback.
def test_board_detail_strips_css_and_script():
    html = """<div class="bbs_view_v4"><table>
      <tr><th>제목</th><td>제목A</td></tr>
      <tr><th>등록일</th><td>2026-01-02</td></tr></table></div>
      <div class="context"><style>.x{display:flex}</style>
      <script>var a=1;</script>실제 본문 텍스트</div>"""
    doc = E.extract_board_detail(html)
    assert "실제 본문 텍스트" in doc.body_text
    assert "{" not in doc.body_text and "display" not in doc.body_text
    assert "var a" not in doc.body_text


def test_board_detail_gallery_no_wholepage_fallback():
    # gallery template WITHOUT .cont_txt/.cont_sub must NOT dump shared chrome/CSS.
    html = """<div class="subContent">
      <style>.videoList ul{display:flex;flex-wrap:wrap}</style>
      체육정보 &gt; 스포츠교실 동영상 검색영역 검색</div>"""
    doc = E.extract_board_detail(html, list_title="컬링경기의 특성")
    assert "{" not in doc.body_text
    assert "videoList" not in doc.body_text
    assert doc.title == "컬링경기의 특성"


# RC6: alternate date labels + regex fallback within the header table.
def test_board_detail_alt_date_label():
    html = """<div class="bbs_view_v4"><table>
      <tr><th>제목</th><td>입찰공고</td></tr>
      <tr><th>공고일</th><td>2026-03-04</td></tr></table></div>
      <div class="context">본문</div>"""
    doc = E.extract_board_detail(html, unit_type="bid")
    assert doc.posted_at == "2026-03-04"


def test_board_detail_date_regex_fallback():
    html = """<div class="bbs_view_v4"><table>
      <tr><th>제목</th><td>T</td></tr></table>
      <p>게시 2026-02-01 조회 3</p></div><div class="context">본문</div>"""
    doc = E.extract_board_detail(html)
    assert doc.posted_at == "2026-02-01"


# RC5: attachments must carry a derived MIME type.
def test_attachment_has_mime():
    html = """<a onclick="fnFileDownAction('/f/p','보고서.pdf','stored_abc.pdf')">d</a>"""
    atts = E.extract_attachments(html)
    assert atts and atts[0].mime == "application/pdf"


# RC2: seed upsert must be idempotent despite NULL columns (SQLite NULL!=NULL).
def test_upsert_source_idempotent_with_null_columns(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    for _ in range(3):
        s.upsert_source(host="h", source_type="board", variant="bs", board_seq=50,
                        menu_seq=583, page_seq=None, book_gbn=None,
                        list_url_tmpl="공지", priority=1)
    n = s.db.execute("SELECT COUNT(*) FROM crawl_source").fetchone()[0]
    assert n == 1
    s.close()


# RC3: starting a run must mark any prior 'running' run as interrupted (no ghosts).
def test_start_run_marks_prior_running_interrupted(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    r1 = s.start_run("full")
    s.start_run("full")
    st = s.db.execute("SELECT status FROM crawl_run WHERE id=?", (r1,)).fetchone()[0]
    assert st == "interrupted"
    s.close()


# RC4: a processed source must record last_crawled_at.
def test_mark_source_crawled(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    sid = s.upsert_source(host="h", source_type="static", page_seq=27, menu_seq=559,
                          list_url_tmpl="x", priority=3)
    s.mark_source_crawled(sid)
    ts = s.db.execute("SELECT last_crawled_at FROM crawl_source WHERE id=?", (sid,)).fetchone()[0]
    assert ts is not None
    s.close()
