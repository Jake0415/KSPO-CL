from __future__ import annotations

import pytest

from kspo_ingest.api.auth.lockout import LoginLockout


@pytest.fixture
def lockout():
    return LoginLockout(max_attempts=5, lockout_seconds=300)


def test_initial_state_not_locked(lockout):
    assert not lockout.is_locked("admin")


def test_record_failures_below_threshold(lockout):
    for _ in range(4):
        lockout.record_failure("admin")
    assert not lockout.is_locked("admin")


def test_lock_after_max_attempts(lockout):
    for _ in range(5):
        lockout.record_failure("admin")
    assert lockout.is_locked("admin")


def test_reset_on_success(lockout):
    for _ in range(3):
        lockout.record_failure("admin")
    lockout.record_success("admin")
    assert not lockout.is_locked("admin")
    for _ in range(4):
        lockout.record_failure("admin")
    assert not lockout.is_locked("admin")


def test_remaining_seconds_when_locked(lockout):
    for _ in range(5):
        lockout.record_failure("admin")
    remaining = lockout.remaining_seconds("admin")
    assert remaining is not None
    assert remaining > 0
    assert remaining <= 300


def test_remaining_seconds_when_not_locked(lockout):
    assert lockout.remaining_seconds("admin") is None
