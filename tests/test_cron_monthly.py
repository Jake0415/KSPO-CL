from __future__ import annotations

import inspect

from kspo_ingest.tasks import cron, worker


def test_monthly_full_enqueues_enqueue_seeds():
    src = inspect.getsource(cron.monthly_full_all)
    assert "enqueue_seeds" in src
    assert 'job_type="full"' in src
    assert 'triggered_by="cron_monthly"' in src


def test_weekly_incremental_removed():
    assert not hasattr(cron, "weekly_incremental_all")
    wsrc = inspect.getsource(worker)
    assert "weekly_incremental_all" not in wsrc
