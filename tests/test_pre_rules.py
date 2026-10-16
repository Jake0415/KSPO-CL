from __future__ import annotations

from kspo_ingest.refine import pre_rules


def test_too_short_dropped():
    r = pre_rules.check("짧은 본문.", title="제목", ko_ratio_threshold=0.30)
    assert r.drop is True
    assert r.reason == "too_short"


def test_9_chars_dropped():
    body = "가" * 9
    r = pre_rules.check(body, title="제목", ko_ratio_threshold=0.30)
    assert r.drop is True
    assert r.reason == "too_short"


def test_10_chars_passes():
    body = "가" * 10
    r = pre_rules.check(body, title="제목", ko_ratio_threshold=0.30)
    assert r.drop is False


def test_login_title_dropped():
    body = "본문 충분한 길이의 한국어 텍스트입니다. " * 5
    r = pre_rules.check(body, title="로그인", ko_ratio_threshold=0.30)
    assert r.drop is True
    assert r.reason == "error_page"


def test_404_title_dropped():
    body = "본문 충분한 길이의 한국어 텍스트입니다. " * 5
    r = pre_rules.check(body, title="404", ko_ratio_threshold=0.30)
    assert r.drop is True
    assert r.reason == "error_page"


def test_page_not_found_case_insensitive():
    body = "본문 충분한 길이의 한국어 텍스트입니다. " * 5
    r = pre_rules.check(body, title="Page Not Found", ko_ratio_threshold=0.30)
    assert r.drop is True
    assert r.reason == "error_page"


def test_korean_ratio_above_threshold_passes():
    body = "한국어 본문이 충분히 들어 있는 페이지입니다. " * 5
    r = pre_rules.check(body, title="공고", ko_ratio_threshold=0.30)
    assert r.drop is False


def test_english_majority_dropped():
    body = "english only paragraph " * 20  # 영문 90% 이상 제외
    r = pre_rules.check(body, title="Notice", ko_ratio_threshold=0.30)
    assert r.drop is True
    assert r.reason == "english_majority"


def test_no_letters_only_digits_falls_through_to_pass():
    """letters=0이면 non_korean 룰을 평가하지 않음. too_short만 평가."""
    body = "12345 " * 25  # 길이 100 이상 + letters=0
    r = pre_rules.check(body, title="제목", ko_ratio_threshold=0.30)
    # letters=0 → non_korean 룰 건너뛰고 통과 (의도된 정책)
    assert r.drop is False


def test_normal_korean_with_short_title_passes():
    body = "한국어 본문 내용이 충분히 들어 있는 페이지입니다. 의미 있는 텍스트. " * 4
    r = pre_rules.check(body, title="공고문 제목", ko_ratio_threshold=0.30)
    assert r.drop is False


# --- empty_list 룰 ---------------------------------------------------------
# 목록이 행을 하나도 렌더하지 못한 페이지는 300자 안팎이라 too_short(100자)를
# 통과해 Q1으로 적재된다. 실제 KSPO 페이지에서 관측된 세 가지 형태를 각각 막는다.


def test_out_of_range_pagination_dropped():
    """'( 10/3 Pages )' — 범위를 벗어난 pageIndex는 빈 목록을 반환한다."""
    body = (
        "대상사업 목록\n총 21건의 게시물이 등록되었습니다. ( 10/3 Pages )\n"
        "사업번호 제목 선정기준 첨부파일 게시일\n"
        "자료가 없습니다. 다른 검색조건을 선택해주세요\n"
        "정보공개 담당자 경영전략팀 02-410-1167 정보공개 책임관 기획조정실"
    )
    r = pre_rules.check(body, title="대상사업 목록", ko_ratio_threshold=0.30)
    assert r.drop is True
    assert r.reason == "empty_list"


def test_in_range_pagination_passes():
    """'( 2/3 Pages )'는 정상 목록 — 드롭하지 않는다."""
    body = (
        "대상사업 목록\n총 21건의 게시물이 등록되었습니다. ( 2/3 Pages )\n"
        "2016-11 스포츠강좌이용권 지원 사업 대국민 서비스 제공사업 첨부파일 2016-05-30\n"
        "2016-10 국민체력100 사업 국민생활에 영향이 큰 주요 서비스 제공사업 2016-05-30\n"
    ) * 2
    r = pre_rules.check(body, title="대상사업 목록", ko_ratio_threshold=0.30)
    assert r.drop is False


def test_empty_count_dropped():
    """'총  건의 게시물' — 건수 자리가 비면 JS 미렌더 목록이다."""
    body = (
        "정보공개목록\n총 \n건의 게시물이 등록되었습니다. \n( / Pages)\n"
        "번호 제목 부서명 생산일자\n정보목록 상세내용 제목 기관명 담당부서명 담당자명\n"
        "정보공개 담당자 총무팀 02-410-1226 정보공개 책임관 경영지원실"
    )
    r = pre_rules.check(body, title="정보공개목록", ko_ratio_threshold=0.30)
    assert r.drop is True
    assert r.reason == "empty_list"


def test_no_data_phrase_in_short_body_dropped():
    body = "공지사항\n" + "검색된 결과가 없습니다\n" + "번호 제목 작성자 등록일 조회수\n" * 5
    r = pre_rules.check(body, title="공지사항", ko_ratio_threshold=0.30)
    assert r.drop is True
    assert r.reason == "empty_list"


def test_no_data_phrase_in_long_body_passes():
    """긴 본문이 안내 문구를 인용한 경우는 오드롭하지 않는다."""
    body = "한국어 본문이 충분히 들어 있는 안내 페이지입니다. " * 60 + "자료가 없습니다"
    assert len(body) > pre_rules.EMPTY_LIST_MAX_LEN
    r = pre_rules.check(body, title="이용안내", ko_ratio_threshold=0.30)
    assert r.drop is False


def test_empty_list_precedes_non_korean():
    """빈 목록은 숫자·머리글 위주라 non_korean으로 먼저 걸리면 원인이 가려진다."""
    body = "list\n( 5/3 Pages )\n" + "1 2 3 4 5 6 7 8 9 0 " * 10
    r = pre_rules.check(body, title="list", ko_ratio_threshold=0.30)
    assert r.drop is True
    assert r.reason == "empty_list"


def test_whitespace_does_not_bypass_minimum_length():
    assert pre_rules.check("     123456789     ", None, ko_ratio_threshold=0.3).drop


def test_language_threshold_is_ignored():
    for body in [
        "中文艺术作品详细资料",
        "艺术作品详细资料和制作年份",
        "한국어 작품 정보 abc",
    ]:
        assert not pre_rules.check(body, None, ko_ratio_threshold=1.0).drop


def test_english_ninety_percent_boundary():
    for body, expected in [
        ("가" * 5 + "a" * 5, False),
        ("가" * 6 + "a" * 4, False),
        ("가" * 4 + "a" * 6, False),
        ("가" * 11 + "a" * 89, False),
        ("가" * 10 + "a" * 90, True),
        ("가" * 9 + "a" * 91, True),
    ]:
        result = pre_rules.check(body, "작품", ko_ratio_threshold=0.3)
        assert result.drop == expected
        if expected:
            assert result.reason == "english_majority"


def test_technical_references_do_not_inflate_english_ratio():
    text = "한국어 작품 정보 안내 https://example.com/english-file 2026-a.pdf 123"
    assert pre_rules.english_ratio(text) == 0
    assert pre_rules.english_ratio("123 !") == 0
    assert pre_rules.english_ratio("汉字汉字汉字汉字汉字 abc") < 0.5
