from kspo_ingest.maintenance.dedup import (
    PageRow, group_by_identity, select_canonical, find_duplicate_groups,
)

U = "https://www.kspo.or.kr/news/main/main.do"
U_HTTP = "http://www.kspo.or.kr/news/main/main.do"


def test_scheme_twins_group_together():
    rows = [
        PageRow(id=1, url=U, scheme="https", depth=1, status="INDEXED"),
        PageRow(id=2, url=U_HTTP, scheme="http", depth=2, status="INDEXED"),
    ]
    groups = group_by_identity(rows)
    assert len(groups) == 1
    assert len(next(iter(groups.values()))) == 2


def test_select_canonical_prefers_https_then_depth_then_indexed_then_id():
    group = [
        PageRow(id=5, url=U_HTTP, scheme="http", depth=1, status="INDEXED"),
        PageRow(id=9, url=U, scheme="https", depth=2, status="CLEANED"),
        PageRow(id=3, url=U, scheme="https", depth=1, status="INDEXED"),
    ]
    assert select_canonical(group).id == 3  # https, depth1, INDEXED


def test_find_duplicate_groups_returns_canonical_and_losers():
    rows = [
        PageRow(id=1, url=U, scheme="https", depth=1, status="INDEXED"),
        PageRow(id=2, url=U_HTTP, scheme="http", depth=2, status="INDEXED"),
        PageRow(id=7, url="https://x.kr/only/one.do", scheme="https", depth=0, status="INDEXED"),
    ]
    dups = find_duplicate_groups(rows)
    assert len(dups) == 1                 # 단독 페이지(id=7)는 제외
    canon, losers = dups[0]
    assert canon.id == 1
    assert [r.id for r in losers] == [2]
