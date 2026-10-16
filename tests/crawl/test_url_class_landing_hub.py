from kspo_ingest.crawl.url_class import is_landing_hub


def test_landing_hub_matches_subsystem_index():
    assert is_landing_hub("https://www.kspo.or.kr/news/main/main.do") is True
    assert is_landing_hub("https://www.kspo.or.kr/kspo/main/main.do") is True
    assert is_landing_hub("/front/main/main.do") is True
    # 대문자 / 쿼리스트링 / 트레일링 슬래시
    assert is_landing_hub("https://x.kr/News/Main/Main.do?menuNo=1") is True
    assert is_landing_hub("https://x.kr/news/main/main.do/") is True


def test_content_do_pages_are_not_hubs():
    assert is_landing_hub("https://www.kspo.or.kr/news/bbs/B0000089/view.do?nttId=1") is False
    assert is_landing_hub("https://www.kspo.or.kr/news/bbs/B0000088/list.do") is False
    assert is_landing_hub("https://www.kspo.or.kr/kspo/contents.do?menuNo=200001") is False
    assert is_landing_hub("/main.do") is False  # /main/ 접두 없음
    assert is_landing_hub("") is False
