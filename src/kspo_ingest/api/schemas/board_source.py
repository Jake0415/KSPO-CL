from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BoardSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_id: int
    list_url: str


class BoardSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain_id: int
    list_url: str
    status: str
    validation_error: str | None = None
    newest_first: bool
    detected_at: datetime
    confirmed_at: datetime | None
    last_refreshed_at: datetime | None
