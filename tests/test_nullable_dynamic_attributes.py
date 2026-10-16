from kspo_ingest.crawl.dynamic import interaction_candidates


def test_valueless_anchor_attributes_do_not_crash():
    assert interaction_candidates("<a href>empty</a>") == []


def test_valueless_optional_attributes_keep_read_controls():
    candidates = interaction_candidates(
        '<button title onclick aria-label>더보기</button><select onchange><option value="a">가</option></select>'
    )
    assert len(candidates) == 2
