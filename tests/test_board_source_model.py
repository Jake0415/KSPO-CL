from __future__ import annotations

from kspo_ingest.db.models import BoardSource, Page


def test_board_source_columns():
    cols = set(BoardSource.__table__.columns.keys())
    assert cols == {
        "id", "domain_id", "list_url", "status", "newest_first",
        "detected_at", "confirmed_at", "last_refreshed_at",
    }


def test_board_source_unique_domain_list_url():
    uqs = [c.name for c in BoardSource.__table__.constraints if "uq" in (c.name or "")]
    assert "uq_board_source_domain_list_url" in uqs


def test_page_has_board_source_id():
    assert "board_source_id" in Page.__table__.columns


def test_domain_is_board_removed():
    from kspo_ingest.db.models import Domain
    assert "is_board" not in Domain.__table__.columns
