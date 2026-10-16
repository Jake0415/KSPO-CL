from __future__ import annotations

from kspo_ingest.attach.mime import mime_for_ext


def test_pdf_mime():
    assert mime_for_ext(".pdf") == "application/pdf"


def test_office_docx_xlsx_pptx():
    assert mime_for_ext(".docx").startswith("application/vnd.openxmlformats")
    assert mime_for_ext(".xlsx").startswith("application/vnd.openxmlformats")
    assert mime_for_ext(".pptx").startswith("application/vnd.openxmlformats")


def test_hwp_mime_korean_format():
    """한국어 한글 — 표준 mimetypes 모듈은 인식 못함, 명시 매핑."""
    assert mime_for_ext(".hwp") == "application/vnd.hancom.hwp"
    assert mime_for_ext(".hwpx") == "application/vnd.hancom.hwpx"


def test_case_insensitive():
    assert mime_for_ext(".PDF") == "application/pdf"
    assert mime_for_ext(".HwP") == "application/vnd.hancom.hwp"


def test_unknown_ext_falls_back_to_octet_stream():
    assert mime_for_ext(".xyz123") == "application/octet-stream"
