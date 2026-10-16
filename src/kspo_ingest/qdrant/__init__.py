from __future__ import annotations

from kspo_ingest.qdrant.adapter import (
    QdrantDirectAdapter,
    QdrantPoint,
    SyncResult,
    UpsertResult,
)
from kspo_ingest.qdrant.bootstrap import EXPECTED_DIM, CollectionStatus, ensure_collection
from kspo_ingest.qdrant.client import get_client, get_mode, reset_client_for_tests
from kspo_ingest.qdrant.payload import PayloadInput, build_payload
from kspo_ingest.qdrant.tags import build_tags

__all__ = [
    "EXPECTED_DIM",
    "CollectionStatus",
    "PayloadInput",
    "QdrantDirectAdapter",
    "QdrantPoint",
    "SyncResult",
    "UpsertResult",
    "build_payload",
    "build_tags",
    "ensure_collection",
    "get_client",
    "get_mode",
    "reset_client_for_tests",
]
