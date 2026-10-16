from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain_id: int
    job_type: str
    seed_urls: list[str] | None = None
    status: str
    triggered_by: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stats: dict[str, Any] | None = None
    error_message: str | None = None
    arq_job_id: str | None = None
    created_at: datetime


class RefreshUrlRequest(BaseModel):
    url: str = Field(min_length=10, max_length=2000)
    force: bool = False

    @field_validator("url")
    @classmethod
    def must_be_http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v


class RefreshUrlOut(BaseModel):
    job_id: int
    page_id: int
    arq_job_id: str | None = None
    created_domain: bool = False
