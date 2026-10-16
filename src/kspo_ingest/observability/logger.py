from __future__ import annotations

import contextvars
import logging
import sys
from typing import Any

import orjson
from loguru import logger

from kspo_ingest.observability.masking import mask
from kspo_ingest.settings import settings

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def _mask_value(v: Any) -> Any:
    """문자열만 마스킹. 길이 제한은 settings.log_max_field_len 기준."""
    if isinstance(v, str):
        return mask(v, max_len=settings.log_max_field_len)
    return v


def _serialize(record: dict[str, Any]) -> str:
    payload: dict[str, Any] = {
        "ts": record["time"].isoformat(),
        "level": record["level"].name,
        "service": record["extra"].get("service", "-"),
        "logger": record["extra"].get("logger", record["name"]),
        "request_id": request_id_var.get() or record["extra"].get("request_id", "-"),
    }
    msg = record["message"]
    payload["event"] = record["extra"].get("event", msg)
    if msg and msg != payload["event"]:
        payload["msg"] = _mask_value(msg)
    for k, v in record["extra"].items():
        if k in {"service", "logger", "request_id", "event"}:
            continue
        payload[k] = _mask_value(v)
    payload["event"] = _mask_value(payload["event"])
    return orjson.dumps(payload).decode()


def _sink(message: Any) -> None:
    record = message.record
    if settings.log_format == "json":
        sys.stderr.write(_serialize(record) + "\n")
    else:
        sys.stderr.write(f"[{record['level'].name}] {record['name']}: {record['message']}\n")
    sys.stderr.flush()


class _InterceptHandler(logging.Handler):
    """uvicorn / sqlalchemy stdlib loggers → loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).bind(
            logger=record.name
        ).log(level, record.getMessage())


_initialized = False


def _init() -> None:
    global _initialized
    if _initialized:
        return
    logger.remove()
    logger.add(_sink, level=settings.log_level, enqueue=False)
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "sqlalchemy", "sqlalchemy.engine"):
        lg = logging.getLogger(name)
        lg.handlers = [_InterceptHandler()]
        lg.propagate = False
    _initialized = True


def get_logger(service: str, logger_name: str) -> Any:
    _init()
    return logger.bind(service=service, logger=logger_name)
