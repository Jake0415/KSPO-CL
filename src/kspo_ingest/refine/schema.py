from __future__ import annotations

from pydantic import BaseModel, Field


class RefinerOutput(BaseModel):
    refined_text: str
    is_meaningful: bool
    summary: str
    keywords: list[str] = Field(max_length=15)


REFINER_JSON_SCHEMA: dict = {
    "name": "RefinerOutput",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["refined_text", "is_meaningful", "summary", "keywords"],
        "properties": {
            "refined_text": {"type": "string"},
            "is_meaningful": {"type": "boolean"},
            "summary": {"type": "string"},
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 15,
            },
        },
    },
    "strict": True,
}
