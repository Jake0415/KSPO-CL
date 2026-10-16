from __future__ import annotations

import inspect

from kspo_ingest.tasks import cron


def test_daily_board_refresh_enqueues_run_board_refresh():
    src = inspect.getsource(cron.daily_board_refresh)
    assert "run_board_refresh" in src
    assert "is_board" not in src  # 구 플래그 제거
    assert 'job_type="board"' in src
