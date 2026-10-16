"""Alembic migration tests.

본 테스트는 PostgreSQL 인스턴스가 필요하다. CI에서는 services.postgres가 가동되며,
로컬에서는 docker compose up postgres 또는 별도 PG가 있어야 한다.

PG 미가용 환경에서는 자동 skip된다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _pg_reachable() -> bool:
    """PG 환경변수가 모두 채워졌으면 True. 실제 connect는 alembic 실행 시 검증."""
    required = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    return all(os.getenv(k) for k in required)


def _alembic_available() -> bool:
    return shutil.which("alembic") is not None


pytestmark = pytest.mark.skipif(
    not _pg_reachable() or not _alembic_available(),
    reason="alembic/PG environment not configured (set POSTGRES_* env vars + install alembic)",
)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_upgrade_then_downgrade_cycle():
    """upgrade head → downgrade base → upgrade head 무오류."""
    _run("upgrade", "head")
    _run("downgrade", "base")
    _run("upgrade", "head")


def test_alembic_current_is_latest_head():
    """upgrade head 후 current가 최신 revision을 가리킴.

    M0.T0.2까지는 0001_init, M1.T1.1 머지 후엔 0002_core_tables.
    revisions 디렉터리에서 latest를 동적으로 결정해 비교한다.
    """
    _run("upgrade", "head")
    heads_out = _run("heads").stdout
    # heads_out 예: "0002_core_tables (head)"
    head_revision = heads_out.strip().split()[0]
    assert head_revision != ""

    current_out = _run("current").stdout
    assert head_revision in current_out
