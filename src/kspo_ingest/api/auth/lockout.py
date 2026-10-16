"""Login lockout — brute-force protection.

After max_attempts failed logins, the account is locked for lockout_seconds.
Uses in-memory storage (single-process admin tool).
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _UserState:
    failures: int = 0
    locked_at: float | None = None


class LoginLockout:
    def __init__(self, *, max_attempts: int = 5, lockout_seconds: int = 300):
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self._state: dict[str, _UserState] = {}

    def _get(self, username: str) -> _UserState:
        if username not in self._state:
            self._state[username] = _UserState()
        return self._state[username]

    def is_locked(self, username: str) -> bool:
        state = self._get(username)
        if state.locked_at is None:
            return False
        elapsed = time.monotonic() - state.locked_at
        if elapsed >= self.lockout_seconds:
            state.failures = 0
            state.locked_at = None
            return False
        return True

    def remaining_seconds(self, username: str) -> int | None:
        state = self._get(username)
        if state.locked_at is None:
            return None
        elapsed = time.monotonic() - state.locked_at
        remaining = self.lockout_seconds - elapsed
        if remaining <= 0:
            state.failures = 0
            state.locked_at = None
            return None
        return int(remaining)

    def record_failure(self, username: str) -> None:
        state = self._get(username)
        state.failures += 1
        if state.failures >= self.max_attempts:
            state.locked_at = time.monotonic()

    def record_success(self, username: str) -> None:
        state = self._get(username)
        state.failures = 0
        state.locked_at = None
