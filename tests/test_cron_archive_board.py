from __future__ import annotations

import inspect

from kspo_ingest.tasks import cron


def test_archive_board_uses_move_points_and_posted_at():
    src = inspect.getsource(cron.archive_expired_board_posts)
    assert "move_points" in src
    assert "posted_at" in src
    assert "qdrant_archive_collection" in src


def test_existing_archive_excludes_board():
    src = inspect.getsource(cron.archive_expired_documents)
    assert "board_source_id" in src  # board 제외 조건 추가됨
