"""Standalone local worker: manual jobs only, local vector storage."""

from urllib.parse import urlsplit

from kspo_ingest.settings import settings
from kspo_ingest.tasks.worker import WorkerSettings as BaseWorkerSettings
from kspo_ingest.tasks.worker import on_startup as base_startup


async def on_startup(ctx):
    if settings.app_env != "local" or urlsplit(settings.qdrant_url).hostname != "qdrant":
        raise RuntimeError("Local worker requires APP_ENV=local and the local qdrant service")
    if settings.postgres_host != "postgres" or urlsplit(settings.redis_url).hostname != "redis":
        raise RuntimeError("Local worker requires the local postgres and redis services")
    if any(
        (
            settings.sonar_base_url,
            settings.sonar_project_id,
            settings.sonar_email,
            settings.sonar_password,
        )
    ):
        raise RuntimeError("Local worker does not permit an external Sonar destination")
    await base_startup(ctx)
    ctx["local_direct_indexing"] = True


class WorkerSettings:
    # ARQ reads the class namespace; inherited attributes are not discovered.
    functions = BaseWorkerSettings.functions
    redis_settings = BaseWorkerSettings.redis_settings
    timezone = BaseWorkerSettings.timezone
    max_jobs = BaseWorkerSettings.max_jobs
    max_tries = BaseWorkerSettings.max_tries
    job_timeout = BaseWorkerSettings.job_timeout
    on_shutdown = BaseWorkerSettings.on_shutdown
    cron_jobs = []
    on_startup = on_startup
