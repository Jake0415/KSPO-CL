from __future__ import annotations


def test_settings_has_board_freshness_days():
    from kspo_ingest.settings import settings
    assert hasattr(settings, "board_freshness_days")
    assert settings.board_freshness_days == 90
