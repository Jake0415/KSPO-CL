import pytest

from kspo_ingest.attach.discovery import discover_attachments, is_attachment_url
from kspo_ingest.crawl.internal_links import discover_internal_links
from kspo_ingest.crawl.readiness import ReadinessPolicy
from kspo_ingest.settings import Settings


@pytest.mark.parametrize(
    "url",
    [
        "https://sportsmuseum.kspo.or.kr/cmm/fms/getImage.do?atchFileId=FILE_1&fileSn=1",
        "https://example.org/cmm/fms/getImage.do?noImgNm=noimage02.png&atchFileId=FILE_2",
        "https://example.org/file/imageDownload.kspo?id=1",
    ],
)
def test_image_handlers_skip_browser_and_preserve_metadata(url):
    assert is_attachment_url(url)
    html = f'<main><a href="{url}">사진</a><img src="{url}" alt="자료 사진"></main>'
    assert discover_internal_links(html, base_url=url, host=url.split("/")[2]) == []
    files = discover_attachments(html, base_url=url)
    assert len(files) == 1
    assert files[0].source_url == url
    assert files[0].mime_type == "image/*"


def test_inline_handler_image_metadata():
    files = discover_attachments(
        '<main><img src="/cmm/fms/getImage.do?id=1" alt="자료"></main>',
        base_url="https://example.org/",
    )
    assert len(files) == 1 and files[0].mime_type == "image/*"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/photosFilmsView.do?idx=1",
        "https://example.org/imageList.do",
        "https://example.org/view.do?noImgNm=noimage.png",
    ],
)
def test_html_gallery_pages_are_allowed(url):
    assert not is_attachment_url(url)


def test_default_deadlines():
    assert ReadinessPolicy().initial_timeout_ms == 8000
    settings = Settings(_env_file=None)
    assert settings.crawl_initial_ready_timeout_ms == 8000
    assert settings.job_timeout_seconds == 43200
