# Landing-hub 적재 제외 + 코퍼스 중복 정리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/main/main.do` 랜딩 허브를 크롤은 유지하되 KB 적재에서만 제외하고, 코퍼스의 scheme 쌍둥이·구버전 해시 중복을 안전하게(dry-run 우선) 정리한다.

**Architecture:** ① 공유 URL 규칙 모듈에 `is_landing_hub()`를 추가하고, 세 진입 태스크가 공통으로 쓰는 단일 chokepoint `resolve_embedding_targets(...)`에서 허브면 빈 컬렉션을 반환해 publish만 스킵한다. ② 순수 로직 모듈(`maintenance/dedup.py`)이 현행 `normalize_url`로 정체성을 재계산해 그룹핑·canonical 선정을 담당하고, 얇은 CLI 스크립트가 Qdrant 삭제·llm_usage 재지정·page 삭제를 dry-run/execute로 수행한다.

**Tech Stack:** Python 3.12, SQLAlchemy(async), ARQ, Qdrant(`QdrantDirectAdapter`), pytest, uv.

## Global Constraints

- 실행: 모든 테스트는 `uv run pytest`로 구동.
- FK: `chunks`/`attachments`/`llm_usage`/`doc_quality` → `pages`는 전부 `ON DELETE CASCADE`. page 삭제 시 파생행 자동 삭제됨.
- Qdrant active 컬렉션: `settings.qdrant_index_name`(=`tilellm`), `settings.qdrant_knowledge_collection`(=`kspo_knowledge`).
- 랜딩 허브 판별 규칙: 정규화 path(소문자)가 `/main/main.do`로 끝남. (frontier 차단용 `is_non_content_url`과 별도 유지.)
- Canonical 선정 우선순위: `https` → 최저 `depth` → `INDEXED` 우선 → 최소 `id`.
- 삭제 순서: Qdrant 포인트 삭제 → `llm_usage.page_id` canonical 재지정 → `pages` row 삭제.
- 정리 스크립트는 **`--dry-run`이 기본**, `--execute`로만 실제 변경.

---

### Task 1: `is_landing_hub()` — 랜딩 허브 판별 (순수함수)

**Files:**
- Modify: `src/kspo_ingest/crawl/url_class.py` (파일 끝에 함수 추가)
- Test: `tests/crawl/test_url_class_landing_hub.py`

**Interfaces:**
- Produces: `is_landing_hub(url_or_path: str) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/crawl/test_url_class_landing_hub.py
from kspo_ingest.crawl.url_class import is_landing_hub


def test_landing_hub_matches_subsystem_index():
    assert is_landing_hub("https://www.kspo.or.kr/news/main/main.do") is True
    assert is_landing_hub("https://www.kspo.or.kr/kspo/main/main.do") is True
    assert is_landing_hub("/front/main/main.do") is True
    # 대문자 / 쿼리스트링 / 트레일링 슬래시
    assert is_landing_hub("https://x.kr/News/Main/Main.do?menuNo=1") is True
    assert is_landing_hub("https://x.kr/news/main/main.do/") is True


def test_content_do_pages_are_not_hubs():
    assert is_landing_hub("https://www.kspo.or.kr/news/bbs/B0000089/view.do?nttId=1") is False
    assert is_landing_hub("https://www.kspo.or.kr/news/bbs/B0000088/list.do") is False
    assert is_landing_hub("https://www.kspo.or.kr/kspo/contents.do?menuNo=200001") is False
    assert is_landing_hub("/main.do") is False  # /main/ 접두 없음
    assert is_landing_hub("") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/crawl/test_url_class_landing_hub.py -v`
Expected: FAIL with `ImportError: cannot import name 'is_landing_hub'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/kspo_ingest/crawl/url_class.py  (파일 끝에 추가)
def is_landing_hub(url_or_path: str) -> bool:
    """True if the URL/path is an eGov subsystem landing hub (`/main/main.do`).

    랜딩 허브는 내용 없는 내비/대시보드 페이지지만 링크가 풍부한 BFS 진입점이다.
    frontier 차단(is_non_content_url)이 아니라 *적재(publish)* 단계에서만 제외하기
    위한 별도 규칙 — crawl·link 발견은 유지한다.
    """
    if not url_or_path:
        return False
    path = urlparse(url_or_path).path if "://" in url_or_path else url_or_path
    return path.lower().rstrip("/").endswith("/main/main.do")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/crawl/test_url_class_landing_hub.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/kspo_ingest/crawl/url_class.py tests/crawl/test_url_class_landing_hub.py
git commit -m "feat(crawl): is_landing_hub — /main/main.do 랜딩 허브 판별"
```

---

### Task 2: publish 게이트에서 허브 제외 (`resolve_embedding_targets` + 4 호출부)

**Files:**
- Modify: `src/kspo_ingest/quality/embedding_policy.py:31-51` (`resolve_embedding_targets` 시그니처+본문)
- Modify: `src/kspo_ingest/tasks/pipeline/enqueue_seeds.py:186`
- Modify: `src/kspo_ingest/tasks/pipeline/run_incremental.py:159`
- Modify: `src/kspo_ingest/tasks/pipeline/refresh_url.py:101`
- Modify: `src/kspo_ingest/tasks/pipeline/board_page.py:87`
- Test: `tests/quality/test_embedding_policy_landing_hub.py`

**Interfaces:**
- Consumes: `is_landing_hub(url) -> bool` (Task 1)
- Produces: `resolve_embedding_targets(score, policy=None, *, url: str | None = None) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/quality/test_embedding_policy_landing_hub.py
from kspo_ingest.quality.embedding_policy import resolve_embedding_targets
from kspo_ingest.quality.scorer import ScoreResult


def _q1() -> ScoreResult:
    # Q1 = 최고 품질(원래라면 tilellm+kspo_knowledge 둘 다 적재)
    return ScoreResult(
        quadrant="Q1", quality_score=0.9, freshness_score=0.9, trust_score=0.9,
    )


def test_landing_hub_url_returns_no_targets():
    assert resolve_embedding_targets(_q1(), url="https://x.kr/news/main/main.do") == []


def test_content_url_keeps_q1_targets():
    assert resolve_embedding_targets(
        _q1(), url="https://x.kr/news/bbs/B1/view.do?nttId=1"
    ) == ["tilellm", "kspo_knowledge"]


def test_url_none_is_backward_compatible():
    assert resolve_embedding_targets(_q1()) == ["tilellm", "kspo_knowledge"]
```

> NOTE: `ScoreResult` 실제 필드는 `src/kspo_ingest/quality/scorer.py`에서 확인해 생성자 인자를 맞출 것. 위 필드명이 다르면 그 정의에 맞춰 `_q1()`만 수정.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/quality/test_embedding_policy_landing_hub.py -v`
Expected: FAIL — `test_landing_hub_url_returns_no_targets`가 `["tilellm","kspo_knowledge"]`를 반환해 `== []` assert 실패.

- [ ] **Step 3: Write minimal implementation**

`src/kspo_ingest/quality/embedding_policy.py` 상단 import 추가:

```python
from kspo_ingest.crawl.url_class import is_landing_hub
```

`resolve_embedding_targets` 시그니처와 본문 앞부분 수정:

```python
def resolve_embedding_targets(
    score: ScoreResult,
    policy: EmbeddingPolicy | None = None,
    *,
    url: str | None = None,
) -> list[str]:
    """ScoreResult의 quadrant에 따라 upsert 대상 컬렉션 목록 반환.

    url이 랜딩 허브면 quadrant와 무관하게 [] 반환 — doc_quality 기록만 하고
    chunk/embed/Qdrant publish는 스킵한다. 순수 함수 — 상태 없음, I/O 없음.
    """
    if url and is_landing_hub(url):
        return []
    if policy is None:
        policy = DEFAULT_POLICY
    ...  # (기존 mapping 로직 그대로)
```

4개 호출부에 `url=` 인자 추가 (각 파일에서 해당 페이지 URL 변수는 `url`):

```python
# enqueue_seeds.py:186 / run_incremental.py:159 / board_page.py:87
targets = resolve_embedding_targets(score, url=url)
```

```python
# refresh_url.py:101  (url = page.url 이 위에서 세팅됨)
targets = resolve_embedding_targets(score, url=url)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/quality/test_embedding_policy_landing_hub.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 회귀 테스트 — 기존 embedding_policy 테스트 유지**

Run: `uv run pytest tests/quality -q`
Expected: 기존 테스트 전부 PASS (url 키워드는 default None이라 하위호환).

- [ ] **Step 6: Commit**

```bash
git add src/kspo_ingest/quality/embedding_policy.py \
        src/kspo_ingest/tasks/pipeline/enqueue_seeds.py \
        src/kspo_ingest/tasks/pipeline/run_incremental.py \
        src/kspo_ingest/tasks/pipeline/refresh_url.py \
        src/kspo_ingest/tasks/pipeline/board_page.py \
        tests/quality/test_embedding_policy_landing_hub.py
git commit -m "feat(quality): 랜딩 허브는 publish 게이트에서 제외 (crawl 유지)"
```

---

### Task 3: dedup 순수 로직 (`maintenance/dedup.py`)

**Files:**
- Create: `src/kspo_ingest/maintenance/__init__.py` (빈 파일)
- Create: `src/kspo_ingest/maintenance/dedup.py`
- Test: `tests/maintenance/test_dedup.py`

**Interfaces:**
- Consumes: `normalize_url(raw) -> tuple[str, str]` (기존, `crawl/url_normalize.py`)
- Produces:
  - `PageRow(id:int, url:str, scheme:str, depth:int, status:str)` (dataclass)
  - `group_by_identity(rows: list[PageRow]) -> dict[str, list[PageRow]]`
  - `select_canonical(group: list[PageRow]) -> PageRow`
  - `find_duplicate_groups(rows: list[PageRow]) -> list[tuple[PageRow, list[PageRow]]]`

- [ ] **Step 1: Write the failing test**

```python
# tests/maintenance/test_dedup.py
from kspo_ingest.maintenance.dedup import (
    PageRow, group_by_identity, select_canonical, find_duplicate_groups,
)

U = "https://www.kspo.or.kr/news/main/main.do"
U_HTTP = "http://www.kspo.or.kr/news/main/main.do"


def test_scheme_twins_group_together():
    rows = [
        PageRow(id=1, url=U, scheme="https", depth=1, status="INDEXED"),
        PageRow(id=2, url=U_HTTP, scheme="http", depth=2, status="INDEXED"),
    ]
    groups = group_by_identity(rows)
    assert len(groups) == 1
    assert len(next(iter(groups.values()))) == 2


def test_select_canonical_prefers_https_then_depth_then_indexed_then_id():
    group = [
        PageRow(id=5, url=U_HTTP, scheme="http", depth=1, status="INDEXED"),
        PageRow(id=9, url=U, scheme="https", depth=2, status="CLEANED"),
        PageRow(id=3, url=U, scheme="https", depth=1, status="INDEXED"),
    ]
    assert select_canonical(group).id == 3  # https, depth1, INDEXED


def test_find_duplicate_groups_returns_canonical_and_losers():
    rows = [
        PageRow(id=1, url=U, scheme="https", depth=1, status="INDEXED"),
        PageRow(id=2, url=U_HTTP, scheme="http", depth=2, status="INDEXED"),
        PageRow(id=7, url="https://x.kr/only/one.do", scheme="https", depth=0, status="INDEXED"),
    ]
    dups = find_duplicate_groups(rows)
    assert len(dups) == 1                 # 단독 페이지(id=7)는 제외
    canon, losers = dups[0]
    assert canon.id == 1
    assert [r.id for r in losers] == [2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/maintenance/test_dedup.py -v`
Expected: FAIL — `ModuleNotFoundError: kspo_ingest.maintenance`

- [ ] **Step 3: Write minimal implementation**

```python
# src/kspo_ingest/maintenance/dedup.py
"""코퍼스 중복(scheme 쌍둥이/구버전 해시) 정리를 위한 순수 로직.

저장된 pages.url_hash는 구/신버전이 섞여 신뢰할 수 없으므로, 현행 normalize_url로
정체성을 재계산해 그룹핑한다. I/O·상태 없음 — DB/Qdrant 작업은 CLI가 담당.
"""
from __future__ import annotations

from dataclasses import dataclass

from kspo_ingest.crawl.url_normalize import normalize_url


@dataclass
class PageRow:
    id: int
    url: str
    scheme: str   # 'http' | 'https'
    depth: int
    status: str


def group_by_identity(rows: list[PageRow]) -> dict[str, list[PageRow]]:
    """현행 normalize_url로 canonical url_hash를 재계산해 hash별로 묶는다."""
    groups: dict[str, list[PageRow]] = {}
    for r in rows:
        _, url_hash = normalize_url(r.url)
        groups.setdefault(url_hash, []).append(r)
    return groups


def select_canonical(group: list[PageRow]) -> PageRow:
    """https > 최저 depth > INDEXED 우선 > 최소 id 순으로 canonical 선정."""
    def key(r: PageRow) -> tuple[int, int, int, int]:
        return (
            0 if r.scheme == "https" else 1,
            r.depth,
            0 if r.status == "INDEXED" else 1,
            r.id,
        )
    return sorted(group, key=key)[0]


def find_duplicate_groups(
    rows: list[PageRow],
) -> list[tuple[PageRow, list[PageRow]]]:
    """그룹 크기>1인 것만 (canonical, [제거 대상...]) 튜플로 반환."""
    out: list[tuple[PageRow, list[PageRow]]] = []
    for group in group_by_identity(rows).values():
        if len(group) > 1:
            canon = select_canonical(group)
            losers = [r for r in group if r.id != canon.id]
            out.append((canon, losers))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/maintenance/test_dedup.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/kspo_ingest/maintenance/__init__.py \
        src/kspo_ingest/maintenance/dedup.py \
        tests/maintenance/test_dedup.py
git commit -m "feat(maintenance): dedup 순수 로직 — 정체성 재계산·canonical 선정"
```

---

### Task 4: 정리 CLI 스크립트 (`scripts/dedup_scheme_twins.py`)

**Files:**
- Create: `scripts/dedup_scheme_twins.py`

**Interfaces:**
- Consumes: `PageRow`, `find_duplicate_groups` (Task 3); `is_landing_hub` (Task 1); `QdrantDirectAdapter`, `settings`, DB 모델(`Page`, `Chunk`, `LlmUsage`).

> NOTE: 이 태스크는 실 DB/Qdrant I/O라 단위테스트 대신 Task 5의 dry-run으로 검증한다. 모델 클래스명(`Chunk`/`ChunkRow`, `LlmUsage`)과 세션 팩토리 획득 방식은 `src/kspo_ingest/db/models.py`·기존 스크립트(`scripts/qdrant_migrate.py`)를 그대로 참고해 맞출 것.

- [ ] **Step 1: 스크립트 작성**

```python
# scripts/dedup_scheme_twins.py
"""코퍼스 scheme 쌍둥이/구버전 해시 중복 정리 + 랜딩 허브 적재 정리.

    # 중복 현황만 리포트 (아무것도 안 지움)
    uv run python scripts/dedup_scheme_twins.py
    # 실제 정리
    uv run python scripts/dedup_scheme_twins.py --execute
    # 이미 적재된 랜딩 허브도 함께 DROPPED 정리
    uv run python scripts/dedup_scheme_twins.py --execute --purge-hubs
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select, update

from kspo_ingest.crawl.url_class import is_landing_hub
from kspo_ingest.db.models import Chunk, LlmUsage, Page  # 실제 클래스명 확인 후 정정
from kspo_ingest.db.session import get_sessionmaker  # 기존 스크립트와 동일 획득 방식
from kspo_ingest.maintenance.dedup import PageRow, find_duplicate_groups
from kspo_ingest.qdrant.adapter import QdrantDirectAdapter
from kspo_ingest.settings import settings


async def _delete_qdrant_points(adapter, page_ids, session):
    """page_ids의 chunks.qdrant_point_id를 active 컬렉션에서 삭제."""
    rows = await session.execute(
        select(Chunk.qdrant_point_id).where(Chunk.page_id.in_(page_ids))
    )
    point_ids = [r[0] for r in rows.all() if r[0]]
    if not point_ids:
        return 0
    for col in (settings.qdrant_index_name, settings.qdrant_knowledge_collection):
        try:
            await adapter.delete_from_collection(col, point_ids)
        except Exception as exc:  # noqa: BLE001 — KB 정합성 우선, 로그만
            print(f"  [warn] qdrant delete skipped ({col}): {exc}")
    return len(point_ids)


async def run(execute: bool, purge_hubs: bool) -> None:
    sm = get_sessionmaker()
    adapter = QdrantDirectAdapter()

    async with sm() as s:
        rows = await s.execute(select(Page.id, Page.url, Page.scheme, Page.depth, Page.status))
        page_rows = [
            PageRow(id=i, url=u, scheme=sch, depth=d, status=st)
            for (i, u, sch, d, st) in rows.all()
        ]

    dups = find_duplicate_groups(page_rows)
    loser_ids = [r.id for _canon, losers in dups for r in losers]
    canon_by_loser = {r.id: canon.id for canon, losers in dups for r in losers}

    print(f"중복 그룹: {len(dups)}개 / 제거 예정 page: {len(loser_ids)}건")

    hub_ids: list[int] = []
    if purge_hubs:
        hub_ids = [
            r.id for r in page_rows
            if r.status == "INDEXED" and is_landing_hub(r.url) and r.id not in loser_ids
        ]
        print(f"적재된 랜딩 허브(DROPPED 예정): {len(hub_ids)}건")

    if not execute:
        # dry-run: Qdrant 포인트 예상 건수만 계산
        async with sm() as s:
            cnt = await s.scalar(
                select(Chunk.id.count()).where(Chunk.page_id.in_(loser_ids + hub_ids))
            ) if (loser_ids or hub_ids) else 0
        print(f"[dry-run] 삭제 예정 Qdrant 포인트(≈chunks): {cnt}")
        print("[dry-run] --execute 없이는 아무것도 변경하지 않음.")
        return

    # ---- execute ----
    async with sm() as s:
        # 1) 중복 loser: Qdrant 포인트 삭제 → llm_usage 재지정 → page 삭제(CASCADE)
        for canon, losers in dups:
            ids = [r.id for r in losers]
            await _delete_qdrant_points(adapter, ids, s)
            await s.execute(
                update(LlmUsage).where(LlmUsage.page_id.in_(ids)).values(page_id=canon.id)
            )
            await s.execute(Page.__table__.delete().where(Page.id.in_(ids)))
            await s.commit()

        # 2) 랜딩 허브: Qdrant 포인트 삭제 → status=DROPPED (page는 유지)
        if hub_ids:
            await _delete_qdrant_points(adapter, hub_ids, s)
            await s.execute(
                update(Page).where(Page.id.in_(hub_ids)).values(status="DROPPED")
            )
            await s.commit()

    print("완료.")


def main() -> None:
    ap = argparse.ArgumentParser(description="코퍼스 중복 정리 + 랜딩 허브 정리")
    ap.add_argument("--execute", action="store_true", help="실제 삭제 수행(미지정 시 dry-run)")
    ap.add_argument("--purge-hubs", action="store_true", help="이미 적재된 랜딩 허브도 DROPPED 정리")
    args = ap.parse_args()
    asyncio.run(run(execute=args.execute, purge_hubs=args.purge_hubs))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: import·모델명 정합성 확인**

Run: `uv run python -c "import ast,sys; ast.parse(open('scripts/dedup_scheme_twins.py').read()); print('syntax ok')"`
그리고 `src/kspo_ingest/db/models.py`에서 `Chunk`/`LlmUsage`/`Page`의 실제 클래스명과 `Chunk.qdrant_point_id` 필드, `get_sessionmaker` 획득 방식을 확인해 import를 실제와 일치시킨다. (불일치 시 이 스텝에서 정정 — 기존 `scripts/qdrant_migrate.py`가 동일 패턴을 이미 사용.)
Expected: `syntax ok` + import가 실제 심볼과 일치.

- [ ] **Step 3: Commit**

```bash
git add scripts/dedup_scheme_twins.py
git commit -m "feat(scripts): dedup_scheme_twins — dry-run 기본 중복/허브 정리 CLI"
```

---

### Task 5: dry-run 검증 (실 DB, 삭제 없음)

**Files:** (없음 — 실행/검증만)

- [ ] **Step 1: dry-run 실행**

Run:
```bash
docker compose -f docker/docker-compose.yml exec -T worker \
  python scripts/dedup_scheme_twins.py --purge-hubs
```
(로컬 .venv로 DB 접근이 되면 `uv run python scripts/dedup_scheme_twins.py --purge-hubs`도 가능. worker 컨테이너 실행이 .env DSN과 가장 일치.)
Expected: "중복 그룹: N개 / 제거 예정 page: M건", "적재된 랜딩 허브(DROPPED 예정): K건", "[dry-run] ... 변경하지 않음." 출력. **DB·Qdrant 무변경.**

- [ ] **Step 2: news/main/main.do 그룹이 리포트에 반영되는지 확인**

Run:
```bash
docker exec kspo-postgres-1 psql -U kspo -d kspo_ingest -tAc \
 "select id,status,scheme,depth from pages where domain_id=1 and url like '%news/main/main.do%' order by id;"
```
Expected: 3 row 그대로(삭제 전). dry-run 리포트의 중복 그룹 수에 이 그룹(제거예정 2건)이 포함되고, 허브 정리 대상에 canonical 1건이 잡히는 것과 정합.

- [ ] **Step 3: 건수 sanity 기록**

dry-run이 보고한 (중복 그룹 수 / 제거 page 수 / 허브 수 / Qdrant 포인트 수)를 이 계획 문서 하단이나 PR 본문에 기록. 이상치(예: 제거 예정이 전체의 대부분)면 **execute 하지 말고** 원인 조사.

> 실제 `--execute`는 이 계획의 범위지만, dry-run 건수를 사람이 확인한 뒤 별도 승인으로 수행한다. (운영 KB 삭제 — 자동 실행 금지.)

---

## Self-Review

**Spec coverage:**
- ①-a 허브 판별 → Task 1 ✅
- ①-b publish chokepoint 차단(4 호출부) → Task 2 ✅
- ①-c 기존 적재 허브 1회성 DROPPED 정리 → Task 4(`--purge-hubs`) + Task 5 ✅
- ②-a 현행 normalize_url 재계산 그룹핑 → Task 3 `group_by_identity` ✅
- ②-b canonical 선정 → Task 3 `select_canonical` ✅
- ②-c Qdrant 삭제→llm_usage 재지정→page 삭제(CASCADE) → Task 4 execute 경로 ✅
- ②-d dry-run 기본/`--execute` → Task 4 + Task 5 ✅
- ②-e canonical 단위테스트 + dry-run sanity → Task 3 + Task 5 ✅

**Placeholder scan:** 코드 스텝 전부 실제 코드 포함. 두 곳의 NOTE(ScoreResult 필드명, 모델 클래스명)는 "실제 정의에 맞춰 확인"이라는 구체 지시 + 참고 파일 명시 — 미확정 placeholder가 아니라 검증 스텝.

**Type consistency:** `PageRow`/`group_by_identity`/`select_canonical`/`find_duplicate_groups` 시그니처가 Task 3 정의와 Task 4 사용에서 일치. `resolve_embedding_targets(score, policy=None, *, url=None)`가 Task 2 정의와 4 호출부에서 일치. `is_landing_hub(url)` Task 1 정의와 Task 2·4 사용 일치.
