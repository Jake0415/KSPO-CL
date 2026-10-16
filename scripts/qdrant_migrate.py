"""Qdrant 컬렉션 이관 — 소스 → 타깃 (HTTP scroll + upsert).

개발 컨테이너(자체 Qdrant)의 적재 데이터를 운영 Qdrant(Tiledesk 등 외부
인스턴스)로 복사한다. 파일 접근이 필요한 snapshot과 달리 HTTP만으로 동작하므로
관리형/원격 인스턴스에도 쓸 수 있다. point ID·벡터·payload를 그대로 보존한다.

사용법:
    python scripts/qdrant_migrate.py \
        --source-url http://localhost:6333 \
        --target-url https://<운영-qdrant>:6333 \
        --target-key <API_KEY> \
        --collections tilellm,kspo_knowledge,kspo_archive

옵션:
    --recreate         타깃에 같은 이름 컬렉션이 있으면 삭제 후 재생성 (기본: 있으면 중단)
    --batch 512        scroll/upsert 배치 크기
    --dry-run          실제 쓰기 없이 소스 개수만 출력

주의:
- 외부 운영 서버에 쓰는 작업이다. 반드시 --target-url/--target-key를 확인하고 실행할 것.
- 컬렉션 설정(3072-dim Cosine, on_disk, INT8 양자화)과 payload 인덱스를
  소스에서 읽어 타깃에 동일하게 생성한다.
"""
from __future__ import annotations

import argparse
import sys
import time

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm


def _connect(url: str, key: str | None) -> QdrantClient:
    return QdrantClient(url=url, api_key=key or None, timeout=120.0)


def _ensure_target_collection(
    src: QdrantClient, dst: QdrantClient, name: str, recreate: bool
) -> None:
    """타깃에 소스와 동일한 설정으로 컬렉션 생성. payload 인덱스도 복제."""
    info = src.get_collection(name)
    params = info.config.params
    vectors = params.vectors  # VectorParams (단일 벡터 구성)

    exists = dst.collection_exists(name)
    if exists and not recreate:
        raise SystemExit(
            f"[{name}] 타깃에 이미 존재. --recreate로 덮어쓰거나 다른 이름을 쓰세요."
        )
    if exists and recreate:
        dst.delete_collection(name)

    dst.create_collection(
        collection_name=name,
        vectors_config=qm.VectorParams(
            size=vectors.size,
            distance=vectors.distance,
            on_disk=getattr(vectors, "on_disk", None),
        ),
        quantization_config=info.config.quantization_config,
        hnsw_config=(
            qm.HnswConfigDiff(
                m=info.config.hnsw_config.m,
                ef_construct=info.config.hnsw_config.ef_construct,
            )
            if info.config.hnsw_config
            else None
        ),
    )

    # payload 인덱스 복제 (keyword/bool/integer/text 등)
    schema = info.payload_schema or {}
    for field, sch in schema.items():
        try:
            dst.create_payload_index(
                collection_name=name,
                field_name=field,
                field_schema=sch.data_type if hasattr(sch, "data_type") else sch,
            )
        except Exception as exc:  # noqa: BLE001 — 인덱스 실패는 치명적이지 않음
            print(f"  [!] payload index '{field}' 생성 스킵: {type(exc).__name__}")


def _copy_points(
    src: QdrantClient, dst: QdrantClient, name: str, batch: int, dry_run: bool
) -> tuple[int, int]:
    """소스 전체를 배치로 읽어 타깃에 upsert. (복사 수, 소스 총수) 반환."""
    src_total = src.count(name, exact=True).count
    if dry_run:
        return 0, src_total

    copied = 0
    offset = None
    while True:
        points, offset = src.scroll(
            collection_name=name,
            limit=batch,
            with_payload=True,
            with_vectors=True,
            offset=offset,
        )
        if not points:
            break
        dst.upsert(
            collection_name=name,
            points=[
                qm.PointStruct(id=p.id, vector=p.vector, payload=p.payload)
                for p in points
            ],
            wait=True,
        )
        copied += len(points)
        print(f"  [{name}] {copied}/{src_total} 복사…", end="\r", flush=True)
        if offset is None:
            break
    print()
    return copied, src_total


def main() -> int:
    ap = argparse.ArgumentParser(description="Qdrant 컬렉션 이관 (source → target)")
    ap.add_argument("--source-url", default="http://localhost:6333")
    ap.add_argument("--source-key", default="")
    ap.add_argument("--target-url", required=True)
    ap.add_argument("--target-key", default="")
    ap.add_argument("--collections", default="tilellm,kspo_knowledge,kspo_archive")
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--recreate", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    names = [c.strip() for c in args.collections.split(",") if c.strip()]
    src = _connect(args.source_url, args.source_key)
    dst = _connect(args.target_url, args.target_key)

    print(f"소스: {args.source_url}")
    print(f"타깃: {args.target_url}")
    print(f"컬렉션: {names}  (dry_run={args.dry_run}, recreate={args.recreate})\n")

    t0 = time.monotonic()
    results = []
    for name in names:
        if not src.collection_exists(name):
            print(f"[{name}] 소스에 없음 — 건너뜀")
            continue
        if not args.dry_run:
            _ensure_target_collection(src, dst, name, args.recreate)
        copied, total = _copy_points(src, dst, name, args.batch, args.dry_run)
        # 검증: 타깃 개수 == 소스 개수
        dst_total = None if args.dry_run else dst.count(name, exact=True).count
        ok = args.dry_run or dst_total == total
        results.append((name, total, copied, dst_total, ok))
        mark = "DRY" if args.dry_run else ("✅" if ok else "❌ 불일치")
        print(f"[{name}] 소스={total} 복사={copied} 타깃={dst_total} {mark}\n")

    dt = time.monotonic() - t0
    print("=" * 50)
    print(f"완료 ({dt:.1f}s)")
    all_ok = all(r[4] for r in results)
    if not args.dry_run and not all_ok:
        print("일부 컬렉션 개수 불일치 — 재실행 또는 로그 확인 필요")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
