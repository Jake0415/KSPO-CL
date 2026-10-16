from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from kspo_ingest.db.base import Base
from kspo_ingest.settings import settings

config = context.config

# 로깅 (alembic.ini의 [loggers] 섹션 적용)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _build_sync_dsn() -> str:
    """Alembic은 동기 드라이버 사용 — psycopg2 또는 psycopg3 사용 가능.

    settings의 asyncpg DSN에서 동기 드라이버로 치환한다.
    런타임 패키지에 psycopg2/psycopg3 부재 시 alembic이 실행 시점에 명확한 오류로 알려준다.
    """
    return (
        f"postgresql+psycopg2://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_build_sync_dsn(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _build_sync_dsn()
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
