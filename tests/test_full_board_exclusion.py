from __future__ import annotations

from kspo_ingest.tasks.pipeline.enqueue_seeds import is_board_owned_link


def test_pagination_link_excluded():
    confirmed = {"https://x.kr/list.do"}
    assert is_board_owned_link("https://x.kr/list.do?pageNo=2", confirmed_list_urls=confirmed) is True


def test_goview_detail_excluded():
    confirmed = {"https://x.kr/list.do"}
    assert is_board_owned_link("https://x.kr/view.do?nttId=63978", confirmed_list_urls=confirmed) is True


def test_general_page_not_excluded():
    confirmed = {"https://x.kr/list.do"}
    assert is_board_owned_link("https://x.kr/about", confirmed_list_urls=confirmed) is False
