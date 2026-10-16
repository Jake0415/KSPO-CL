from __future__ import annotations

from kspo_ingest.attach.discovery import (
    DiscoveredAttachment,
    discover_attachments,
    url_hash_sha256,
)

BASE = "https://www.kspo.or.kr/notice/123"


def test_discovers_office_and_pdf_links():
    html = """
    <html><body>
      <a href="/files/notice.pdf">공고문 PDF</a>
      <a href="/files/data.xlsx">통계자료</a>
      <a href="/files/plan.docx">계획서</a>
      <a href="/files/slides.pptx">발표자료</a>
    </body></html>
    """
    found = discover_attachments(html, base_url=BASE)
    exts = {a.ext for a in found}
    assert exts == {".pdf", ".xlsx", ".docx", ".pptx"}
    assert all(a.source_url.startswith("https://www.kspo.or.kr/") for a in found)


def test_hwp_is_included_as_metadata_only():
    """v2.0 Lite — HWP도 동일하게 메타 기록 대상."""
    html = '<a href="/files/공고.hwp">한글 공고</a>'
    found = discover_attachments(html, base_url=BASE)
    assert len(found) == 1
    assert found[0].ext == ".hwp"
    assert found[0].mime_type == "application/vnd.hancom.hwp"


def test_image_metadata_saved_video_ignored():
    html = """
    <a href="/img/banner.jpg">배너</a>
    <a href="/img/logo.PNG">로고</a>
    <a href="/video/intro.mp4">소개영상</a>
    <a href="/files/notice.pdf">공고</a>
    """
    found = discover_attachments(html, base_url=BASE)
    assert {a.ext for a in found} == {".pdf", ".jpg", ".png"}


def test_relative_urls_become_absolute():
    html = '<a href="files/notice.pdf">공고</a>'
    found = discover_attachments(html, base_url=BASE)
    # urljoin은 path 마지막 segment를 교체. base_url에서 'notice/123' 위치를 기준.
    assert len(found) == 1
    assert found[0].source_url.endswith("files/notice.pdf")
    assert found[0].source_url.startswith("https://www.kspo.or.kr")


def test_filename_query_param_kspo_pattern():
    """KSPO 게시판 패턴 — /download?file_name=공고.pdf&id=123 등."""
    html = '<a href="/board/download?file_name=공고문.pdf&id=42">다운로드</a>'
    found = discover_attachments(html, base_url=BASE)
    assert len(found) == 1
    assert found[0].ext == ".pdf"
    assert found[0].file_name == "공고문.pdf"


def test_case_insensitive_extension():
    html = '<a href="/files/REPORT.PDF">리포트</a>'
    found = discover_attachments(html, base_url=BASE)
    assert len(found) == 1
    assert found[0].ext == ".pdf"


def test_javascript_and_anchor_links_skipped():
    html = """
    <a href="javascript:download(42)">JS 다운</a>
    <a href="#top">최상단</a>
    <a href="mailto:admin@kspo.or.kr">문의</a>
    <a href="/files/real.pdf">실제 첨부</a>
    """
    found = discover_attachments(html, base_url=BASE)
    assert len(found) == 1
    assert found[0].ext == ".pdf"


def test_duplicate_urls_deduplicated():
    html = """
    <a href="/files/x.pdf">PDF</a>
    <a href="/files/x.pdf">동일 첨부 2회</a>
    """
    found = discover_attachments(html, base_url=BASE)
    assert len(found) == 1


def test_url_hash_sha256_is_deterministic_64_hex():
    h = url_hash_sha256("https://a.com/x.pdf")
    assert len(h) == 64
    assert int(h, 16)
    assert h == url_hash_sha256("https://a.com/x.pdf")


def test_empty_html_returns_empty():
    assert discover_attachments("", base_url=BASE) == []
    assert discover_attachments("<html></html>", base_url=BASE) == []


def test_dataclass_returned():
    html = '<a href="/x.pdf">공고</a>'
    found = discover_attachments(html, base_url=BASE)
    assert isinstance(found[0], DiscoveredAttachment)


def test_body_image_metadata_and_download_filename():
    html = '<main><img src="/uploads/photo.png"><nav><img src="/logo.png"></nav></main>'
    html += '<a href="/download.do?fileName=guide.pdf">첨부</a>'
    found = discover_attachments(html, base_url=BASE)
    assert {a.file_name for a in found} == {"photo.png", "guide.pdf"}
    assert any(a.mime_type == "image/png" for a in found)
