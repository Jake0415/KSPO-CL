"""E2E 테스트 conftest — docker-compose.test.yml stack을 세션 스코프로 부팅.

기본 pytest 실행에서는 `e2e` marker가 deselect되어 본 fixture가 호출되지 않는다.
명시적으로 `pytest -m e2e tests/e2e/` 실행 시에만 docker stack을 띄운다.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_COMPOSE_FILE = (
    Path(__file__).resolve().parent.parent.parent
    / "docker"
    / "docker-compose.test.yml"
)


@pytest.fixture(scope="session")
def docker_test_stack():
    """Bring up postgres/redis/qdrant test containers, run migrations, then teardown."""
    cmd_up = [
        "docker", "compose", "-f", str(_COMPOSE_FILE),
        "up", "-d", "--wait",
    ]
    subprocess.run(cmd_up, check=True)

    # alembic upgrade head — 호스트 환경변수로 test stack 가리키도록 설정 후 실행
    env = os.environ.copy()
    env["POSTGRES_HOST"] = "localhost"
    env["POSTGRES_PORT"] = "55432"
    env["POSTGRES_DB"] = "kspo_ingest_test"
    env["POSTGRES_USER"] = "kspo"
    env["POSTGRES_PASSWORD"] = "kspo"
    env["REDIS_URL"] = "redis://localhost:56379/0"
    env["QDRANT_URL"] = "http://localhost:56333"
    env["KB_BOOTSTRAP"] = "managed"
    env["QDRANT_INDEX_NAME"] = "kspo_test"
    env.setdefault("OPENAI_API_KEY", "sk-test")
    env.setdefault(
        "ADMIN_PASSWORD_BCRYPT",
        "$2b$12$placeholder0000000000000000000000000000000000000000",
    )
    env.setdefault(
        "SESSION_SECRET", "ci_dummy_session_secret_at_least_32_bytes_long"
    )

    subprocess.run(
        ["alembic", "upgrade", "head"],
        check=True,
        env=env,
        cwd=str(_COMPOSE_FILE.parent.parent),
    )

    yield {
        "postgres_dsn": "postgresql+asyncpg://kspo:kspo@localhost:55432/kspo_ingest_test",
        "redis_url": "redis://localhost:56379/0",
        "qdrant_url": "http://localhost:56333",
        "qdrant_collection": "kspo_test",
    }

    subprocess.run(
        ["docker", "compose", "-f", str(_COMPOSE_FILE), "down", "-v"],
        check=False,
    )
