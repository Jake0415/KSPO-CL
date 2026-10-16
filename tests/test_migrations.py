"""Migration 0002_core_tables tests.

PG·alembic 가용 시에만 실행. 부재 시 자동 skip.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_TABLES = {
    "domains",
    "crawl_jobs",
    "pages",
    "attachments",
    "chunks",
    "llm_usage",
    "alembic_version",
}

EXPECTED_INDEXES = {
    "idx_jobs_status",
    "idx_jobs_domain",
    "idx_pages_status",
    "idx_pages_domain",
    "idx_attachments_page",
    "idx_chunks_page",
    "idx_chunks_qdrant",
    "idx_chunks_kb_status",
    "idx_llm_usage_job",
}

CHUNKS_EXPECTED_COLUMNS = {
    "id",
    "chunk_id_sha1",
    "qdrant_point_id",
    "page_id",
    "attachment_id",
    "is_attachment",
    "chunk_index",
    "token_len",
    "embedding_model",
    "embedding_version",
    "embed_status",
    "kb_status",
    "created_at",
    "updated_at",
}


def _pg_reachable() -> bool:
    required = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    return all(os.getenv(k) for k in required)


def _alembic_available() -> bool:
    return shutil.which("alembic") is not None


pytestmark = pytest.mark.skipif(
    not _pg_reachable() or not _alembic_available(),
    reason="alembic/PG environment not configured",
)


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def _connect():
    """psycopg2 연결 (alembic이 이미 의존성 — pyproject.toml에 포함)."""
    import psycopg2

    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ["POSTGRES_PORT"]),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"],
    )


@pytest.fixture
def upgraded_pg():
    """alembic upgrade head — 0002_core_tables까지 적용. teardown은 downgrade base로 복원."""
    _alembic("upgrade", "head")
    yield
    _alembic("downgrade", "base")


def test_upgrade_creates_six_tables_plus_alembic(upgraded_pg):
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name"
        )
        names = {r[0] for r in cur.fetchall()}
    assert EXPECTED_TABLES.issubset(names), f"missing: {EXPECTED_TABLES - names}"


def test_upgrade_creates_all_indexes(upgraded_pg):
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname='public'")
        indexes = {r[0] for r in cur.fetchall()}
    missing = EXPECTED_INDEXES - indexes
    assert not missing, f"missing indexes: {missing}"


def test_chunks_has_all_13_columns_in_single_create(upgraded_pg):
    """add_column 분리 단계 없이 단일 CREATE TABLE로 모든 컬럼이 들어왔는지 검증."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='chunks'"
        )
        columns = {r[0] for r in cur.fetchall()}
    missing = CHUNKS_EXPECTED_COLUMNS - columns
    assert not missing, f"chunks missing columns: {missing}"


def test_downgrade_removes_all_core_tables(upgraded_pg):
    """upgrade head → downgrade -1 → 6 테이블 삭제, alembic_version만 남음 (revision=0001_init)."""
    _alembic("downgrade", "-1")
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name"
        )
        names = {r[0] for r in cur.fetchall()}
    core = {"domains", "crawl_jobs", "pages", "attachments", "chunks", "llm_usage"}
    leftover = core & names
    assert not leftover, f"core tables still present after downgrade: {leftover}"

    out = _alembic("current").stdout
    assert "0001_init" in out


def test_chunks_attachment_cascade_on_delete(upgraded_pg):
    """attachment 삭제 시 chunks(is_attachment=true)도 cascade 삭제되는지 검증."""
    import uuid

    with _connect() as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            # domains
            cur.execute(
                "INSERT INTO domains (host, status, scheme) "
                "VALUES (%s, DEFAULT, DEFAULT) RETURNING id",
                ("test-cascade.example",),
            )
            # status 컬럼은 domains에 없음 — 위 SQL은 의도적으로 테이블 스키마를 따른다 (수정).
        conn.rollback()

        # 다시: domains는 host만 필수 (다른 컬럼은 server_default 적용)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO domains (host) VALUES (%s) RETURNING id",
                ("test-cascade.example",),
            )
            domain_id = cur.fetchone()[0]

            cur.execute(
                "INSERT INTO pages (domain_id, url, url_hash, status) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (domain_id, "https://test-cascade.example/p", "a" * 40, "INDEXED"),
            )
            page_id = cur.fetchone()[0]

            cur.execute(
                "INSERT INTO attachments "
                "(page_id, domain_id, source_url, file_hash, storage_path) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (page_id, domain_id, "https://x/y.pdf", "f" * 64, "/data/x"),
            )
            att_id = cur.fetchone()[0]

            cur.execute(
                "INSERT INTO chunks "
                "(chunk_id_sha1, qdrant_point_id, page_id, attachment_id, is_attachment, "
                " chunk_index, token_len, embedding_model) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    "c" * 40,
                    str(uuid.uuid4()),
                    page_id,
                    att_id,
                    True,
                    0,
                    100,
                    "text-embedding-3-large",
                ),
            )
            chunk_id = cur.fetchone()[0]
            conn.commit()

            # delete attachment → chunk should cascade
            cur.execute("DELETE FROM attachments WHERE id=%s", (att_id,))
            conn.commit()

            cur.execute("SELECT 1 FROM chunks WHERE id=%s", (chunk_id,))
            assert cur.fetchone() is None, "chunk 행이 cascade 삭제되지 않음"


def test_idempotent_upgrade(upgraded_pg):
    """upgrade head를 두 번 호출해도 변동 없음 (이미 head)."""
    _alembic("upgrade", "head")
    out = _alembic("current").stdout
    assert "0002_core_tables" in out
