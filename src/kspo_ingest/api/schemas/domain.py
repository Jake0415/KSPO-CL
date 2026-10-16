from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DomainBase(BaseModel):
    host: str = Field(min_length=3, max_length=253)
    scheme: str = Field(default="https", pattern=r"^https?$")
    start_url: str | None = None
    display_name: str | None = None
    max_depth: int = Field(default=10, ge=0, le=50)
    max_pages: int = Field(default=30_000, ge=1, le=1_000_000)
    rate_limit_rps: Decimal = Field(default=Decimal("1.5"), ge=Decimal("0.1"), le=Decimal("20"))
    concurrency: int = Field(default=4, ge=1, le=32)
    use_playwright: bool = False
    respect_robots: bool = True
    user_agent: str | None = None
    allow_patterns: list[str] | None = None
    deny_patterns: list[str] | None = None
    selector_blacklist: list[str] | None = None
    incremental_cron: str | None = "0 3 * * 0"
    incremental_enabled: bool | None = True
    is_active: bool = True

    @field_validator("start_url")
    @classmethod
    def valid_start_url(cls, value):
        from kspo_ingest.crawl.start_url import parse_start_url
        return parse_start_url(value) if value else None

    @field_validator("host")
    @classmethod
    def host_lowercase_and_no_path(cls, v: str) -> str:
        v = v.strip().lower()
        if v.startswith(("http://", "https://")):
            raise ValueError("host should not include scheme")
        if "/" in v:
            raise ValueError("host should not include path")
        return v


class DomainCreate(DomainBase):
    pass


class DomainUpdate(BaseModel):
    """PATCH — 모든 필드 optional. extra=forbid로 오타 방지."""

    model_config = ConfigDict(extra="forbid")

    start_url: str | None = None
    display_name: str | None = None
    max_depth: int | None = Field(default=None, ge=0, le=50)
    max_pages: int | None = Field(default=None, ge=1, le=1_000_000)
    rate_limit_rps: Decimal | None = Field(default=None, ge=Decimal("0.1"), le=Decimal("20"))
    concurrency: int | None = Field(default=None, ge=1, le=32)
    use_playwright: bool | None = None
    respect_robots: bool | None = None
    user_agent: str | None = None
    allow_patterns: list[str] | None = None
    deny_patterns: list[str] | None = None
    selector_blacklist: list[str] | None = None
    incremental_cron: str | None = None
    incremental_enabled: bool | None = None
    is_active: bool | None = None


class DomainOut(DomainBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
