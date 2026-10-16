# 게시판 크롤 재설계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 게시판을 URL 단위(`board_source`)로 관리하며, 월간 full 크롤 중 자동 탐지 → 관리자 확인 → 일간 목록 파싱 크롤(3개월 윈도우) → 만료분 kspo_archive 이동까지 완성한다.

**Architecture:** `is_board` 도메인 플래그를 `board_source` 테이블로 대체. 월간 full(`enqueue_seeds`)이 게시판 목록 후보를 자동 탐지(candidate), 관리자가 confirm하면 일간 `run_board_refresh`가 목록을 페이지네이션하며 3개월 내 게시글만 기존 per-page 파이프라인으로 적재. `posted_at` 90일 경과분은 재임베딩 없이 Qdrant `move_points`로 kspo_archive 이동.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 async, Alembic, ARQ, Qdrant(async client), FastAPI, Pydantic v2, pytest + pytest-asyncio(auto) + fakeredis + pytest-postgresql. UI: Next.js 16 / React 19 / React Query.

## Global Constraints

- 스펙: `docs/superpowers/specs/2026-07-06-board-crawl-design.md` (verbatim 결정 원본)
- 비동기 일관: asyncio + httpx + asyncpg + arq. ORM SQLAlchemy 2.0 async.
- import: `from __future__ import annotations`, 절대 import. lint: ruff (line 100).
- 컬렉션 이름은 하드코딩 금지 — `settings.qdrant_index_name`(tilellm), `settings.qdrant_knowledge_collection`(kspo_knowledge), `settings.qdrant_archive_collection`(kspo_archive) 사용.
- 3개월 창은 `settings.board_freshness_days`(기본 90) 사용. 신규 env 추가 금지.
- 신규 백엔드 모듈은 단위 테스트 동반(>80% 라인). UI(`web/`)는 lint + `tsc` + 수동 검증(단위 테스트 없음 — 프로젝트 규약).
- 임베딩 모델 하드코딩 금지, 원본 본문 로그 출력 금지.
- Alembic head는 현재 `0006`. 신규 revision id `0007`, `down_revision="0006"`.

---

### Task 1: `board_source` 테이블 + `Page.board_source_id` (모델 & 마이그레이션)

**Files:**
- Modify: `src/kspo_ingest/db/models.py` (Domain에서 `is_board` 제거, `BoardSource` 추가, `Page.board_source_id` 추가)
- Create: `migrations/versions/0007_board_source.py`
- Test: `tests/test_board_source_model.py`

**Interfaces:**
- Produces: `BoardSource` ORM (`id, domain_id, list_url, status, newest_first, detected_at, confirmed_at, last_refreshed_at`), `Page.board_source_id: int | None`.

- [ ] **Step 1: 실패하는 모델 테스트 작성**

`tests/test_board_source_model.py`:
```python
from __future__ import annotations

from kspo_ingest.db.models import BoardSource, Page


def test_board_source_columns():
    cols = set(BoardSource.__table__.columns.keys())
    assert cols == {
        "id", "domain_id", "list_url", "status", "newest_first",
        "detected_at", "confirmed_at", "last_refreshed_at",
    }


def test_board_source_unique_domain_list_url():
    uqs = [c.name for c in BoardSource.__table__.constraints if "uq" in (c.name or "")]
    assert "uq_board_source_domain_list_url" in uqs


def test_page_has_board_source_id():
    assert "board_source_id" in Page.__table__.columns


def test_domain_is_board_removed():
    from kspo_ingest.db.models import Domain
    assert "is_board" not in Domain.__table__.columns
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_board_source_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'BoardSource'`

- [ ] **Step 3: 모델 구현**

`src/kspo_ingest/db/models.py` — `Domain` 클래스에서 `is_board` 컬럼 라인 삭제. 파일 상단 import에 필요한 것 확인 후, `Page` 클래스에 컬럼 추가(`status` 컬럼 아래):
```python
    board_source_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("board_source.id", ondelete="SET NULL")
    )
```
`Attachment` 클래스 앞(또는 `Domain` 뒤)에 신규 클래스 추가:
```python
class BoardSource(Base):
    __tablename__ = "board_source"
    __table_args__ = (
        UniqueConstraint(
            "domain_id", "list_url", name="uq_board_source_domain_list_url"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="CASCADE")
    )
    list_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="candidate")
    newest_first: Mapped[bool] = mapped_column(Boolean, server_default="true")
    detected_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_refreshed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
```

- [ ] **Step 4: 모델 테스트 통과 확인**

Run: `python -m pytest tests/test_board_source_model.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 마이그레이션 작성**

`migrations/versions/0007_board_source.py`:
```python
"""board_source table + pages.board_source_id, drop domains.is_board.

Revision ID: 0007
Revises: 0006
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "board_source",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("domain_id", sa.BigInteger, sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("list_url", sa.Text, nullable=False),
        sa.Column("status", sa.Text, server_default="candidate", nullable=False),
        sa.Column("newest_first", sa.Boolean, server_default="true", nullable=False),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("domain_id", "list_url", name="uq_board_source_domain_list_url"),
    )
    op.create_index("ix_board_source_status", "board_source", ["status"])
    op.add_column(
        "pages",
        sa.Column("board_source_id", sa.BigInteger, sa.ForeignKey("board_source.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_pages_board_source_id", "pages", ["board_source_id"])

    # 기존 is_board=true 도메인 루트를 candidate board_source로 이관
    op.execute(
        """
        INSERT INTO board_source (domain_id, list_url, status)
        SELECT id, scheme || '://' || host, 'candidate'
        FROM domains WHERE is_board = true
        ON CONFLICT (domain_id, list_url) DO NOTHING
        """
    )
    op.drop_column("domains", "is_board")


def downgrade() -> None:
    op.add_column("domains", sa.Column("is_board", sa.Boolean, server_default="false", nullable=False))
    op.drop_index("ix_pages_board_source_id", table_name="pages")
    op.drop_column("pages", "board_source_id")
    op.drop_index("ix_board_source_status", table_name="board_source")
    op.drop_table("board_source")
```

- [ ] **Step 6: 마이그레이션 적용 검증 (테스트 DB)**

Run: `python -m pytest tests/test_migrations.py -v` (있으면). 없으면 스킵하고 다음 스텝에서 전체 스위트로 검증.
Expected: PASS 또는 (파일 없음 → skip)

- [ ] **Step 7: 기존 `is_board` 참조 컴파일 오류 제거**

`grep -rn "is_board" src/` 결과의 남은 참조는 Task 6에서 cron 교체 시 함께 제거한다. 여기서는 모델/마이그레이션만. 임시로 `cron.py`의 `daily_board_refresh`가 `Domain.is_board`를 참조하면 import 에러가 나므로, Task 6 전까지 스위트가 깨질 수 있음 — Task 1~6은 한 브랜치에서 순차 진행하고 Task 6 완료 후 전체 스위트를 돌린다.

- [ ] **Step 8: 커밋**

```bash
git add src/kspo_ingest/db/models.py migrations/versions/0007_board_source.py tests/test_board_source_model.py
git commit -m "feat(db): board_source 테이블 + pages.board_source_id, is_board 제거 (0007)"
```

---

### Task 2: `board.py` — 공지행 스킵 · `classify_board_list` · `build_page_url`

**Files:**
- Modify: `src/kspo_ingest/crawl/board.py`
- Test: `tests/test_board.py` (기존 파일에 추가)

**Interfaces:**
- Produces:
  - `extract_board_items(html, *, base_url) -> list[BoardItem]` (기존, 공지행 스킵 추가)
  - `classify_board_list(html, *, base_url) -> BoardSignal` — `BoardSignal(is_board: bool, score: int, has_pagination: bool, has_goview: bool, dated_rows: int)`
  - `build_page_url(list_url: str, page_no: int) -> str`
  - `is_within_freshness(posted_at, *, freshness_days=90, now=None) -> bool` (기존)

- [ ] **Step 1: 실패 테스트 작성 (tests/test_board.py 하단 추가)**

```python
from kspo_ingest.crawl.board import (
    BoardSignal,
    build_page_url,
    classify_board_list,
    extract_board_items,
)


_LIST_HTML = """
<table>
 <tr class="notice"><td>공지</td><td><a href="/view.do?nttId=1">중요</a></td><td>2020.01.01</td></tr>
 <tr><td>10</td><td><a href="/view.do?nttId=10">글A</a></td><td>2026.07.01</td></tr>
 <tr><td>9</td><td><a href="/view.do?nttId=9">글B</a></td><td>2026.06.20</td></tr>
</table>
<div class="paging"><a href="?pageNo=2">2</a><a href="?pageNo=3">3</a></div>
"""


def test_extract_board_items_skips_notice_row():
    items = extract_board_items(_LIST_HTML, base_url="https://x.kr/list.do")
    urls = [it.url for it in items]
    assert "https://x.kr/view.do?nttId=1" not in urls  # 공지 스킵
    assert "https://x.kr/view.do?nttId=10" in urls
    assert len(items) == 2


def test_classify_board_list_two_signals_true():
    sig = classify_board_list(_LIST_HTML, base_url="https://x.kr/bbs/list.do")
    assert isinstance(sig, BoardSignal)
    assert sig.has_pagination is True
    assert sig.dated_rows >= 2
    assert sig.is_board is True


def test_classify_non_board_single_signal_false():
    html = "<table><tr><td>x</td></tr></table>"
    sig = classify_board_list(html, base_url="https://x.kr/about")
    assert sig.is_board is False


def test_build_page_url_appends_pageno():
    assert build_page_url("https://x.kr/list.do", 3) == "https://x.kr/list.do?pageNo=3"
    assert build_page_url("https://x.kr/list.do?menuNo=5", 2) == "https://x.kr/list.do?menuNo=5&pageNo=2"
    assert build_page_url("https://x.kr/list.do?pageNo=1", 4) == "https://x.kr/list.do?pageNo=4"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_board.py -v -k "notice or classify or build_page"`
Expected: FAIL — `ImportError: cannot import name 'classify_board_list'`

- [ ] **Step 3: 구현**

`src/kspo_ingest/crawl/board.py` 수정. 상단 import에 `re` 존재. 신규 추가:
```python
import re as _re  # 이미 re import 되어 있으면 재사용
from dataclasses import dataclass

_NOTICE_MARKERS = ("공지", "notice")


def _is_notice_row(row) -> bool:
    cls = (row.attributes.get("class") or "").lower()
    if "notice" in cls:
        return True
    first_cell = row.css_first("td")
    if first_cell is not None:
        txt = first_cell.text(strip=True).lower()
        if txt in ("공지", "notice"):
            return True
    return False
```
`extract_board_items` 루프 안 `for row in tree.css("tr"):` 바로 아래에 `if _is_notice_row(row): continue` 추가.

파일 하단에 신규 함수:
```python
@dataclass
class BoardSignal:
    is_board: bool
    score: int
    has_pagination: bool
    has_goview: bool
    dated_rows: int


_PAGE_SIG_RE = re.compile(r"(?:pageNo|page)=\d+")
_GOVIEW_SIG_RE = re.compile(r"(?:goView|fn\w*View)\(\s*['\"]\d+['\"]\s*\)")


def classify_board_list(html: str, *, base_url: str) -> BoardSignal:
    """게시판 목록 페이지 판정 — 3신호 중 2개 이상이면 board."""
    if not html:
        return BoardSignal(False, 0, False, False, 0)
    has_pagination = bool(_PAGE_SIG_RE.search(html))
    has_goview = bool(_GOVIEW_SIG_RE.search(html))
    dated_rows = len(extract_board_items(html, base_url=base_url))
    has_dates = dated_rows >= 5
    score = int(has_pagination) + int(has_goview) + int(has_dates)
    return BoardSignal(
        is_board=score >= 2,
        score=score,
        has_pagination=has_pagination,
        has_goview=has_goview,
        dated_rows=dated_rows,
    )


def build_page_url(list_url: str, page_no: int) -> str:
    """list_url에 pageNo 파라미터를 부착/치환."""
    stripped = re.sub(r"[&?]pageNo=\d+", "", list_url)
    sep = "&" if "?" in stripped else "?"
    return f"{stripped}{sep}pageNo={page_no}"
```
(`_is_notice_row`는 `row.attributes`/`row.css_first`를 쓰는 selectolax 노드 메서드 — 기존 `extract_board_items`가 이미 `row.css_first`를 사용하므로 API 일치.)

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_board.py -v`
Expected: PASS (기존 + 신규 모두)

- [ ] **Step 5: 커밋**

```bash
git add src/kspo_ingest/crawl/board.py tests/test_board.py
git commit -m "feat(crawl): board 공지행 스킵 + classify_board_list + build_page_url"
```

---

### Task 3: 자동 탐지 배선 — `extract_links`에서 board_source candidate upsert

**Files:**
- Create: `src/kspo_ingest/crawl/board_detect.py` (DB upsert 헬퍼 — board.py는 순수 유지)
- Modify: `src/kspo_ingest/tasks/pipeline/extract_links.py`
- Test: `tests/test_board_detect.py`

**Interfaces:**
- Consumes: `classify_board_list` (Task 2), `BoardSource` (Task 1).
- Produces: `async def upsert_board_candidate(s, *, domain_id, list_url) -> None` — status='candidate'로 upsert(중복/이미 confirmed면 무시).

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_board_detect.py`:
```python
from __future__ import annotations

import pytest

from kspo_ingest.crawl.board_detect import upsert_board_candidate
from kspo_ingest.db.models import BoardSource, Domain


@pytest.mark.asyncio
async def test_upsert_creates_candidate(db_session):
    d = Domain(host="x.kr", scheme="https")
    db_session.add(d)
    await db_session.commit()
    await upsert_board_candidate(db_session, domain_id=d.id, list_url="https://x.kr/list.do")
    rows = (await db_session.execute(BoardSource.__table__.select())).all()
    assert len(rows) == 1
    assert rows[0].status == "candidate"


@pytest.mark.asyncio
async def test_upsert_idempotent_and_keeps_confirmed(db_session):
    d = Domain(host="y.kr", scheme="https")
    db_session.add(d)
    await db_session.commit()
    db_session.add(BoardSource(domain_id=d.id, list_url="https://y.kr/list.do", status="confirmed"))
    await db_session.commit()
    await upsert_board_candidate(db_session, domain_id=d.id, list_url="https://y.kr/list.do")
    src = (await db_session.execute(
        BoardSource.__table__.select().where(BoardSource.domain_id == d.id)
    )).all()
    assert len(src) == 1
    assert src[0].status == "confirmed"  # confirmed 유지
```
(주: `db_session` fixture는 기존 `tests/conftest.py`의 pytest-postgresql 기반 async 세션을 사용. 기존 DB 테스트 파일에서 쓰는 fixture 이름과 동일하게 맞춘다 — 예: `tests/test_gate.py` 참조.)

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_board_detect.py -v`
Expected: FAIL — `ModuleNotFoundError: kspo_ingest.crawl.board_detect`

- [ ] **Step 3: 구현**

`src/kspo_ingest/crawl/board_detect.py`:
```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.db.models import BoardSource


async def upsert_board_candidate(
    s: AsyncSession, *, domain_id: int, list_url: str
) -> None:
    """게시판 목록 후보를 candidate로 기록. 이미 존재하면(어떤 status든) 무시."""
    existing = (
        await s.execute(
            select(BoardSource).where(
                BoardSource.domain_id == domain_id,
                BoardSource.list_url == list_url,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    s.add(BoardSource(domain_id=domain_id, list_url=list_url, status="candidate"))
    await s.commit()
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_board_detect.py -v`
Expected: PASS

- [ ] **Step 5: extract_links에 탐지 배선**

`src/kspo_ingest/tasks/pipeline/extract_links.py` — 이미 page HTML과 session_factory에 접근하는 지점이 있다(내부에서 `discover_internal_links` 호출). HTML/base_url/domain_id를 아는 위치에서 아래를 추가:
```python
from kspo_ingest.crawl.board import classify_board_list
from kspo_ingest.crawl.board_detect import upsert_board_candidate
# ... 링크 추출 직후, html/base_url/domain_id/session_factory가 있는 곳:
sig = classify_board_list(html, base_url=base_url)
if sig.is_board and session_factory is not None:
    async with session_factory() as s:
        await upsert_board_candidate(s, domain_id=domain_id, list_url=base_url)
```
(정확한 변수명은 파일 내 기존 지역변수에 맞춘다. `html`이 없으면 fetch 결과 본문을 재사용하거나, `discover_internal_links`에 넘기는 것과 동일한 HTML 변수를 사용.)

- [ ] **Step 6: 전체 board 관련 스위트 통과 확인**

Run: `python -m pytest tests/test_board_detect.py tests/test_extract_links.py -v`
Expected: PASS (기존 extract_links 테스트 회귀 없음)

- [ ] **Step 7: 커밋**

```bash
git add src/kspo_ingest/crawl/board_detect.py src/kspo_ingest/tasks/pipeline/extract_links.py tests/test_board_detect.py
git commit -m "feat(pipeline): full 크롤 중 게시판 목록 자동 탐지 → candidate 기록"
```

---

### Task 4: `QdrantDirectAdapter.move_points` (재임베딩 없이 컬렉션 이동)

**Files:**
- Modify: `src/kspo_ingest/qdrant/adapter.py`
- Test: `tests/test_qdrant_move_points.py`

**Interfaces:**
- Consumes: `self.client` (AsyncQdrantClient).
- Produces: `async def move_points(self, from_col: str, to_col: str, point_ids: list[UUID]) -> int` — 이동한 포인트 수 반환.

- [ ] **Step 1: 실패 테스트 작성 (fake client)**

`tests/test_qdrant_move_points.py`:
```python
from __future__ import annotations

from uuid import uuid4

import pytest

from kspo_ingest.qdrant.adapter import QdrantDirectAdapter


class _FakeRecord:
    def __init__(self, pid, vector, payload):
        self.id = str(pid)
        self.vector = vector
        self.payload = payload


class _FakeClient:
    def __init__(self):
        self.upserted = {}
        self.deleted = {}
        self._store = {}

    async def retrieve(self, collection_name, ids, with_vectors, with_payload):
        return [self._store[i] for i in ids if i in self._store]

    async def upsert(self, collection_name, points, wait):
        self.upserted[collection_name] = points

    async def delete(self, collection_name, points_selector, wait):
        self.deleted[collection_name] = points_selector


@pytest.mark.asyncio
async def test_move_points_moves_vectors_without_reembed():
    pid = uuid4()
    adapter = QdrantDirectAdapter()
    fake = _FakeClient()
    fake._store[str(pid)] = _FakeRecord(pid, [0.1] * 3072, {"page_content": "x"})
    adapter.client = fake

    moved = await adapter.move_points("tilellm", "kspo_archive", [pid])
    assert moved == 1
    assert "kspo_archive" in fake.upserted
    assert "tilellm" in fake.deleted


@pytest.mark.asyncio
async def test_move_points_empty_noop():
    adapter = QdrantDirectAdapter()
    adapter.client = _FakeClient()
    assert await adapter.move_points("a", "b", []) == 0
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_qdrant_move_points.py -v`
Expected: FAIL — `AttributeError: 'QdrantDirectAdapter' object has no attribute 'move_points'`

- [ ] **Step 3: 구현**

`src/kspo_ingest/qdrant/adapter.py` — `delete_from_collection` 아래에 추가(상단에 `from qdrant_client import models as qmodels` 존재 확인):
```python
    async def move_points(
        self, from_col: str, to_col: str, point_ids: list[UUID]
    ) -> int:
        """from_col의 포인트를 벡터+페이로드째로 to_col에 재upsert 후 from_col에서 삭제.

        재임베딩 없이 컬렉션 이동(아카이브). retrieve로 벡터 회수 → upsert → delete.
        """
        if not point_ids:
            return 0
        ids = [str(pid) for pid in point_ids]
        records = await self.client.retrieve(
            collection_name=from_col,
            ids=ids,
            with_vectors=True,
            with_payload=True,
        )
        if not records:
            return 0
        await self.client.upsert(
            collection_name=to_col,
            points=[
                qmodels.PointStruct(id=r.id, vector=r.vector, payload=r.payload)
                for r in records
            ],
            wait=True,
        )
        await self.client.delete(
            collection_name=from_col,
            points_selector=qmodels.PointIdsList(points=ids),
            wait=True,
        )
        log.bind(
            event="qdrant_move_points",
            from_col=from_col,
            to_col=to_col,
            count=len(records),
        ).info("move ok")
        return len(records)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_qdrant_move_points.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/kspo_ingest/qdrant/adapter.py tests/test_qdrant_move_points.py
git commit -m "feat(qdrant): move_points — 재임베딩 없이 컬렉션 간 포인트 이동"
```

---

### Task 5: `get_or_create_page` 확장 — `board_source_id` + `posted_at` 주입

**Files:**
- Modify: `src/kspo_ingest/tasks/pipeline/helpers.py`
- Test: `tests/test_helpers_page.py`

**Interfaces:**
- Produces: `get_or_create_page(s, *, domain_id, url, depth, board_source_id=None, posted_at=None) -> Page` — 신규 페이지 생성 시 두 필드 세팅, 기존 페이지는 posted_at이 없을 때만 보강.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_helpers_page.py`:
```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kspo_ingest.db.models import Domain
from kspo_ingest.tasks.pipeline.helpers import get_or_create_page


@pytest.mark.asyncio
async def test_create_page_with_board_fields(db_session):
    d = Domain(host="b.kr", scheme="https")
    db_session.add(d)
    await db_session.commit()
    dt = datetime(2026, 7, 1, tzinfo=UTC)
    page = await get_or_create_page(
        db_session, domain_id=d.id, url="https://b.kr/view.do?nttId=1",
        depth=0, board_source_id=None, posted_at=dt,
    )
    assert page.posted_at == dt
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_helpers_page.py -v`
Expected: FAIL — `TypeError: get_or_create_page() got an unexpected keyword argument 'board_source_id'`

- [ ] **Step 3: 구현**

`src/kspo_ingest/tasks/pipeline/helpers.py` — 시그니처와 본문 수정:
```python
async def get_or_create_page(
    s: AsyncSession,
    *,
    domain_id: int,
    url: str,
    depth: int,
    board_source_id: int | None = None,
    posted_at: "datetime | None" = None,
) -> Page:
    normalized, url_hash = normalize_url(url)
    existing = (
        await s.execute(
            select(Page).where(Page.domain_id == domain_id, Page.url_hash == url_hash)
        )
    ).scalar_one_or_none()
    if existing is not None:
        # 목록에서 확보한 posted_at/board_source_id 보강(비어있을 때만)
        changed = False
        if posted_at is not None and existing.posted_at is None:
            existing.posted_at = posted_at
            changed = True
        if board_source_id is not None and existing.board_source_id is None:
            existing.board_source_id = board_source_id
            changed = True
        if changed:
            await s.commit()
        return existing

    page = Page(
        domain_id=domain_id,
        url=normalized,
        url_hash=url_hash,
        status="DISCOVERED",
        depth=depth,
        board_source_id=board_source_id,
        posted_at=posted_at,
    )
    s.add(page)
    await s.commit()
    await s.refresh(page)
    return page
```
(`datetime` import가 파일 상단에 이미 있으므로 문자열 애노테이션 대신 직접 `datetime | None` 사용 가능. 기존 import 확인 후 맞춘다.)

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_helpers_page.py -v`
Expected: PASS

- [ ] **Step 5: 회귀 확인 (기존 fetch_page 호출 호환 — 신규 인자 optional)**

Run: `python -m pytest tests/ -k "fetch_page or helpers" -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add src/kspo_ingest/tasks/pipeline/helpers.py tests/test_helpers_page.py
git commit -m "feat(pipeline): get_or_create_page에 board_source_id/posted_at 주입"
```

---

### Task 6: `run_board_refresh` 태스크 + per-page 체인 재사용

**Files:**
- Create: `src/kspo_ingest/tasks/pipeline/run_board_refresh.py`
- Create: `src/kspo_ingest/tasks/pipeline/board_page.py` (per-detail-page 처리 헬퍼 — `run_incremental._process_one` 로직을 board용으로 래핑)
- Test: `tests/test_run_board_refresh.py`

**Interfaces:**
- Consumes: `extract_board_items`, `build_page_url`, `is_within_freshness` (Task 2); `get_or_create_page` (Task 5); 기존 `fetch_page/clean_page/refine_page/score_document/chunk_and_index`; `start_job/finish_job/is_cancelled` (`tasks/jobs.py`).
- Produces: `async def run_board_refresh(ctx, *, job_id, domain_id) -> None`; `async def process_board_page(ctx, *, job_id, domain_id, board_source_id, url, posted_at) -> None`.

- [ ] **Step 1: 실패 테스트 작성 (페이지네이션 중단 로직)**

`tests/test_run_board_refresh.py`:
```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kspo_ingest.crawl.board import build_page_url, extract_board_items, is_within_freshness


def test_pagination_stop_when_all_out_of_window():
    now = datetime(2026, 7, 6, tzinfo=UTC)
    old = (now - timedelta(days=200)).strftime("%Y.%m.%d")
    html = f'<table><tr><td>1</td><td><a href="/view.do?nttId=1">a</a></td><td>{old}</td></tr></table>'
    items = extract_board_items(html, base_url="https://x.kr/list.do")
    in_window = [it for it in items if is_within_freshness(it.posted_at, freshness_days=90, now=now)]
    assert len(items) == 1
    assert len(in_window) == 0  # → 호출자는 페이지네이션 중단


def test_build_page_url_used_for_pagination():
    assert build_page_url("https://x.kr/list.do", 2).endswith("pageNo=2")
```
(전체 태스크 통합 테스트는 fakeredis+pg가 필요해 무겁다. 여기서는 중단 판정 로직의 순수 단위 테스트로 검증하고, 통합 동작은 Step 5 수동 스모크로 확인.)

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_run_board_refresh.py -v`
Expected: PASS (Task 2가 이미 함수 제공 → 이 테스트는 로직 가드로 통과. board_page/run_board_refresh 모듈 부재 컴파일 확인은 Step 4에서)

- [ ] **Step 3: `board_page.py` 구현 (per-detail 체인)**

`src/kspo_ingest/tasks/pipeline/board_page.py` — `run_incremental._process_one`을 참고하되, `get_or_create_page`에 `board_source_id`/`posted_at`을 넘기도록 fetch를 감싼다. `fetch_page`는 내부에서 `get_or_create_page(depth=0)`을 호출하므로, board 게시글은 먼저 페이지를 만들어 두고 fetch가 그 행을 재사용하게 한다:
```python
from __future__ import annotations

from datetime import datetime

from kspo_ingest.db.models import Domain, Page
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.quality.embedding_policy import resolve_embedding_targets
from kspo_ingest.quality.gate import upsert_doc_quality
from kspo_ingest.quality.scorer import ScorerInput, score_document
from kspo_ingest.tasks.pipeline.chunk_and_index import chunk_and_index
from kspo_ingest.tasks.pipeline.clean_page import clean_page
from kspo_ingest.tasks.pipeline.fetch_page import fetch_page
from kspo_ingest.tasks.pipeline.helpers import get_or_create_page
from kspo_ingest.tasks.pipeline.refine_page import refine_page

log = get_logger("worker", "board_page")


async def process_board_page(
    ctx: dict, *, job_id: int, domain_id: int,
    board_source_id: int, url: str, posted_at: datetime,
) -> None:
    """게시판 상세 1건: page 선생성(board_source_id+posted_at) → 기존 per-page 체인."""
    session_factory = ctx["session_factory"]
    async with session_factory() as s:
        await get_or_create_page(
            s, domain_id=domain_id, url=url, depth=0,
            board_source_id=board_source_id, posted_at=posted_at,
        )

    page_id = await fetch_page(ctx, job_id=job_id, domain_id=domain_id, url=url, depth=0)
    if page_id is None:
        return
    cleaned = await clean_page(ctx, job_id=job_id, page_id=page_id)
    if cleaned is None or cleaned.get("skipped"):
        return
    refined = await refine_page(
        ctx, job_id=job_id, page_id=page_id,
        title=cleaned["title"], body_text=cleaned["body_text"],
        content_hash=cleaned["content_hash"],
    )
    if not refined or not refined.get("refined"):
        return
    r = refined["refined"]
    async with session_factory() as s:
        domain = await s.get(Domain, domain_id)
        domain_host = domain.host if domain else ""
        page_row = await s.get(Page, page_id)
        page_posted_at = getattr(page_row, "posted_at", None) if page_row else None
    score = score_document(ScorerInput(
        title=cleaned["title"], body_text=cleaned["body_text"],
        extraction_method=cleaned.get("method", "heuristic"),
        posted_at=page_posted_at, summary=r.get("summary"),
        keywords=r.get("keywords") or [], is_meaningful=True, domain_host=domain_host,
    ))
    async with session_factory() as s:
        await upsert_doc_quality(s, page_id=page_id, score=score)
    targets = resolve_embedding_targets(score)
    if not targets:
        return
    await chunk_and_index(
        ctx, job_id=job_id, page_id=page_id, refined_text=r["refined_text"],
        summary=r.get("summary"), keywords=r.get("keywords") or [],
        quality_score=score.quality_score, quadrant=score.quadrant,
        freshness_score=score.freshness_score, trust_score=score.trust_score,
        collections=targets,
    )
```

- [ ] **Step 4: `run_board_refresh.py` 구현 (목록 파싱 + 페이지네이션)**

`src/kspo_ingest/tasks/pipeline/run_board_refresh.py`:
```python
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from kspo_ingest.crawl.board import build_page_url, extract_board_items, is_within_freshness
from kspo_ingest.db.models import BoardSource
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.settings import settings
from kspo_ingest.tasks.jobs import finish_job, is_cancelled, start_job
from kspo_ingest.tasks.pipeline.board_page import process_board_page

log = get_logger("worker", "run_board_refresh")

MAX_BOARD_PAGES = 200


async def run_board_refresh(ctx: dict, *, job_id: int, domain_id: int) -> None:
    session_factory = ctx["session_factory"]
    fetcher = ctx["smart_fetcher"]  # worker on_startup의 SmartFetcher (ctx 키 확인 후 맞춤)
    now = datetime.now(UTC)
    freshness = settings.board_freshness_days

    async with session_factory() as s:
        await start_job(s, job_id)
        srcs = list((await s.execute(
            select(BoardSource).where(
                BoardSource.domain_id == domain_id,
                BoardSource.status == "confirmed",
            )
        )).scalars().all())

    for src in srcs:
        page_no = 1
        while page_no <= MAX_BOARD_PAGES:
            async with session_factory() as s:
                if await is_cancelled(s, job_id):
                    break
            list_url = build_page_url(src.list_url, page_no)
            result = await fetcher.fetch(list_url)
            html = getattr(result, "text", None) or ""
            items = extract_board_items(html, base_url=list_url)
            if not items:
                break
            in_window = [it for it in items if is_within_freshness(it.posted_at, freshness_days=freshness, now=now)]
            for it in in_window:
                try:
                    await process_board_page(
                        ctx, job_id=job_id, domain_id=domain_id,
                        board_source_id=src.id, url=it.url, posted_at=it.posted_at,
                    )
                except Exception as exc:  # per-글 실패는 격리
                    log.bind(event="board_page_error", url=it.url, err=str(exc)).warning("skip")
            if not in_window and src.newest_first:
                break
            page_no += 1
        async with session_factory() as s:
            db_src = await s.get(BoardSource, src.id)
            if db_src:
                db_src.last_refreshed_at = now
                await s.commit()

    async with session_factory() as s:
        await finish_job(s, job_id, status="SUCCESS")
```
(주: `ctx`의 fetcher 키 이름은 `tasks/worker.py:on_startup`에서 확인 — `smart_fetcher`/`fetcher` 중 실제 키에 맞춘다. `result.text` 속성명은 `FetchResult` 정의(`crawl/fetcher.py:24`)에 맞춘다.)

- [ ] **Step 5: 컴파일 + 단위 통과 확인**

Run: `python -c "import kspo_ingest.tasks.pipeline.run_board_refresh, kspo_ingest.tasks.pipeline.board_page"`
Expected: (출력 없음 = import 성공)
Run: `python -m pytest tests/test_run_board_refresh.py -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add src/kspo_ingest/tasks/pipeline/run_board_refresh.py src/kspo_ingest/tasks/pipeline/board_page.py tests/test_run_board_refresh.py
git commit -m "feat(pipeline): run_board_refresh — 목록 파싱+3개월 페이지네이션 중단"
```

---

### Task 7: 일간 board cron 교체 + worker 등록

**Files:**
- Modify: `src/kspo_ingest/tasks/cron.py` (`daily_board_refresh` 재작성)
- Modify: `src/kspo_ingest/tasks/worker.py` (task 등록 + cron 유지)
- Test: `tests/test_cron_board.py`

**Interfaces:**
- Consumes: `run_board_refresh` (Task 6), `BoardSource` (Task 1).
- Produces: `daily_board_refresh(ctx)` — confirmed board_source가 있는 active 도메인마다 `job_type="board"` CrawlJob enqueue.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_cron_board.py`:
```python
from __future__ import annotations

import inspect

from kspo_ingest.tasks import cron


def test_daily_board_refresh_enqueues_run_board_refresh():
    src = inspect.getsource(cron.daily_board_refresh)
    assert "run_board_refresh" in src
    assert "is_board" not in src           # 구 플래그 제거
    assert 'job_type="board"' in src
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_cron_board.py -v`
Expected: FAIL (기존 daily_board_refresh는 run_incremental 호출 + is_board 참조)

- [ ] **Step 3: `daily_board_refresh` 재작성**

`src/kspo_ingest/tasks/cron.py` — `daily_board_refresh` 함수 본문을 교체. `Domain.is_board` 대신 confirmed BoardSource 존재 도메인을 대상으로:
```python
async def daily_board_refresh(ctx: dict) -> dict:
    """매일 04:00 KST — confirmed board_source가 있는 active 도메인의 board Job enqueue."""
    session_factory = ctx["session_factory"]
    pool = await _get_pool()
    enqueued = 0
    async with session_factory() as s:
        rows = await s.execute(
            select(Domain.id)
            .join(BoardSource, BoardSource.domain_id == Domain.id)
            .where(Domain.is_active.is_(True), BoardSource.status == "confirmed")
            .distinct()
        )
        domain_ids = [r[0] for r in rows.all()]
        for did in domain_ids:
            active = await s.scalar(
                select(func.count()).select_from(CrawlJob).where(
                    CrawlJob.domain_id == did,
                    CrawlJob.status.in_(["PENDING", "RUNNING"]),
                )
            )
            if active and active > 0:
                continue
            job = CrawlJob(domain_id=did, job_type="board", status="PENDING",
                           triggered_by="cron_board", stats=empty_stats())
            s.add(job)
            await s.commit()
            await s.refresh(job)
            arq_job = await pool.enqueue_job("run_board_refresh", job_id=job.id, domain_id=did)
            job.arq_job_id = arq_job.job_id if arq_job else None
            await s.commit()
            enqueued += 1
    log.bind(event="daily_board_refresh", enqueued=enqueued).info("daily board cron tick")
    return {"enqueued": enqueued}
```
파일 상단 import에 `BoardSource` 추가.

- [ ] **Step 4: worker에 task 등록**

`src/kspo_ingest/tasks/worker.py` — import 추가 및 `functions` 리스트에 `run_board_refresh` 추가:
```python
from kspo_ingest.tasks.pipeline.run_board_refresh import run_board_refresh
# functions = [ ... , run_board_refresh, ]
```
기존 `cron(daily_board_refresh, hour={4}, minute={0}, ...)` 유지.

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_cron_board.py -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add src/kspo_ingest/tasks/cron.py src/kspo_ingest/tasks/worker.py tests/test_cron_board.py
git commit -m "feat(cron): daily_board_refresh → run_board_refresh 배선, is_board 제거"
```

---

### Task 8: `archive_expired_board_posts` cron (kspo_archive 이동)

**Files:**
- Modify: `src/kspo_ingest/tasks/cron.py` (신규 함수 + 기존 archive에 board 제외 조건)
- Modify: `src/kspo_ingest/tasks/worker.py` (cron 등록)
- Test: `tests/test_cron_archive_board.py`

**Interfaces:**
- Consumes: `move_points` (Task 4), `mark_archived` (`quality/gate.py`), `Page`(board_source_id/posted_at), `Chunk`.
- Produces: `archive_expired_board_posts(ctx)`.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_cron_archive_board.py`:
```python
from __future__ import annotations

import inspect

from kspo_ingest.tasks import cron


def test_archive_board_uses_move_points_and_posted_at():
    src = inspect.getsource(cron.archive_expired_board_posts)
    assert "move_points" in src
    assert "posted_at" in src
    assert "qdrant_archive_collection" in src


def test_existing_archive_excludes_board():
    src = inspect.getsource(cron.archive_expired_documents)
    assert "board_source_id" in src  # board 제외 조건 추가됨
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_cron_archive_board.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'archive_expired_board_posts'`

- [ ] **Step 3: 신규 cron 구현 + 기존 archive 수정**

`src/kspo_ingest/tasks/cron.py` 하단에 추가:
```python
async def archive_expired_board_posts(ctx: dict) -> dict:
    """매일 05:30 KST — posted_at이 board_freshness_days 경과한 게시글을 kspo_archive로 이동."""
    from datetime import UTC, datetime, timedelta

    session_factory = ctx["session_factory"]
    cutoff = datetime.now(UTC) - timedelta(days=settings.board_freshness_days)
    adapter = QdrantDirectAdapter()
    active_cols = [settings.qdrant_index_name, settings.qdrant_knowledge_collection]
    archive_col = settings.qdrant_archive_collection
    archived = 0

    async with session_factory() as s:
        rows = await s.execute(
            select(Page).where(
                Page.board_source_id.is_not(None),
                Page.posted_at < cutoff,
                Page.status == "INDEXED",
            )
        )
        pages = list(rows.scalars().all())
        for page in pages:
            chunk_rows = await s.execute(
                select(ChunkRow.qdrant_point_id).where(ChunkRow.page_id == page.id)
            )
            point_ids = [r[0] for r in chunk_rows.all() if r[0]]
            if point_ids:
                for col in active_cols:
                    try:
                        await adapter.move_points(col, archive_col, point_ids)
                    except Exception:
                        log.bind(event="board_archive_move_skip", collection=col, page_id=page.id).debug("skip")
            await mark_archived(s, page.id)
            archived += 1
    log.bind(event="archive_expired_board_posts", archived=archived).info("board archive tick")
    return {"archived": archived}
```
그리고 기존 `archive_expired_documents`의 `select(DocQuality).where(...)`에 board 제외 조건 추가 — DocQuality엔 board_source_id가 없으므로 Page 조인으로:
```python
        rows = await s.execute(
            select(DocQuality)
            .join(Page, Page.id == DocQuality.page_id)
            .where(
                DocQuality.freshness_score < threshold,
                DocQuality.quadrant.in_(["Q1", "Q2", "Q3"]),
                DocQuality.archived_at.is_(None),
                Page.board_source_id.is_(None),   # 게시글 제외
            )
        )
```
import에 `Page` 확인/추가.

- [ ] **Step 4: worker cron 등록**

`src/kspo_ingest/tasks/worker.py` — import에 `archive_expired_board_posts` 추가, `cron_jobs`에:
```python
        cron(archive_expired_board_posts, hour={5}, minute={30}, run_at_startup=False),
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_cron_archive_board.py -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add src/kspo_ingest/tasks/cron.py src/kspo_ingest/tasks/worker.py tests/test_cron_archive_board.py
git commit -m "feat(cron): archive_expired_board_posts — posted_at 만료분 kspo_archive 이동"
```

---

### Task 9: 월간 full cron 신설 + 주간 incremental 제거

**Files:**
- Modify: `src/kspo_ingest/tasks/cron.py` (`monthly_full_all` 추가, `weekly_incremental_all` 제거)
- Modify: `src/kspo_ingest/tasks/worker.py` (cron 교체, `cron_count` 로그 수정)
- Test: `tests/test_cron_monthly.py`

**Interfaces:**
- Produces: `monthly_full_all(ctx)` — active 도메인마다 `job_type="full"` + `enqueue_seeds` enqueue.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_cron_monthly.py`:
```python
from __future__ import annotations

import inspect

from kspo_ingest.tasks import cron, worker


def test_monthly_full_enqueues_enqueue_seeds():
    src = inspect.getsource(cron.monthly_full_all)
    assert "enqueue_seeds" in src
    assert 'job_type="full"' in src
    assert 'triggered_by="cron_monthly"' in src


def test_weekly_incremental_removed():
    assert not hasattr(cron, "weekly_incremental_all")
    wsrc = inspect.getsource(worker)
    assert "weekly_incremental_all" not in wsrc
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_cron_monthly.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

`src/kspo_ingest/tasks/cron.py` — `weekly_incremental_all` 함수 전체 삭제, 신규 추가:
```python
async def monthly_full_all(ctx: dict) -> dict:
    """매월 1일 02:00 KST — active 도메인 전체 full 크롤(enqueue_seeds)."""
    session_factory = ctx["session_factory"]
    pool = await _get_pool()
    enqueued = 0
    async with session_factory() as s:
        rows = await s.execute(select(Domain).where(Domain.is_active.is_(True)))
        domains = list(rows.scalars().all())
        for d in domains:
            active = await s.scalar(
                select(func.count()).select_from(CrawlJob).where(
                    CrawlJob.domain_id == d.id,
                    CrawlJob.status.in_(["PENDING", "RUNNING"]),
                )
            )
            if active and active > 0:
                continue
            job = CrawlJob(domain_id=d.id, job_type="full", status="PENDING",
                           triggered_by="cron_monthly", stats=empty_stats())
            s.add(job)
            await s.commit()
            await s.refresh(job)
            arq_job = await pool.enqueue_job("enqueue_seeds", job_id=job.id, domain_id=d.id)
            job.arq_job_id = arq_job.job_id if arq_job else None
            await s.commit()
            enqueued += 1
    log.bind(event="monthly_full_all", enqueued=enqueued).info("monthly full cron tick")
    return {"enqueued": enqueued}
```

- [ ] **Step 4: worker cron 교체**

`src/kspo_ingest/tasks/worker.py` — `weekly_incremental_all` import/cron 제거. import에 `monthly_full_all` 추가. `cron_jobs`의 weekly 블록을 아래로 교체(ARQ `month` 스펙은 매월 1일 → `day={1}`):
```python
        cron(monthly_full_all, day={1}, hour={2}, minute={0}, run_at_startup=False),
```
`on_startup`의 `cron_count=5` 로그 문자열을 실제 개수(현재 7)로 수정.

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_cron_monthly.py -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add src/kspo_ingest/tasks/cron.py src/kspo_ingest/tasks/worker.py tests/test_cron_monthly.py
git commit -m "feat(cron): monthly_full_all 신설 + weekly_incremental_all 제거"
```

---

### Task 10: 월간 full에서 게시판 하위 링크 제외

**Files:**
- Modify: `src/kspo_ingest/tasks/pipeline/enqueue_seeds.py` (frontier 투입 전 board 제외 필터)
- Test: `tests/test_full_board_exclusion.py`

**Interfaces:**
- Consumes: `BoardSource`(confirmed list_url), `Page.board_source_id`.
- Produces: full BFS가 (a) confirmed board_source의 list_url 하위 `pageNo≥2`/`goView` 링크를 frontier에 넣지 않고, (b) `board_source_id`가 세팅된 페이지를 재처리하지 않음.

- [ ] **Step 1: 실패 테스트 작성 (순수 필터 함수)**

`tests/test_full_board_exclusion.py`:
```python
from __future__ import annotations

from kspo_ingest.tasks.pipeline.enqueue_seeds import is_board_owned_link


def test_pagination_link_excluded():
    confirmed = {"https://x.kr/list.do"}
    assert is_board_owned_link("https://x.kr/list.do?pageNo=2", confirmed_list_urls=confirmed) is True


def test_goview_detail_excluded():
    confirmed = {"https://x.kr/list.do"}
    assert is_board_owned_link("https://x.kr/view.do?nttId=63978", confirmed_list_urls=confirmed) is True


def test_general_page_not_excluded():
    confirmed = {"https://x.kr/list.do"}
    assert is_board_owned_link("https://x.kr/about", confirmed_list_urls=confirmed) is False
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_full_board_exclusion.py -v`
Expected: FAIL — `ImportError: cannot import name 'is_board_owned_link'`

- [ ] **Step 3: 구현 (필터 함수 + frontier 배선)**

`src/kspo_ingest/tasks/pipeline/enqueue_seeds.py` — 모듈 함수 추가:
```python
def is_board_owned_link(url: str, *, confirmed_list_urls: set[str]) -> bool:
    """이 URL이 confirmed board_source(list_url) 소유의 페이지네이션/상세 링크인가.

    board list_url의 경로 prefix를 공유하면서 pageNo= 또는 view.do?nttId= 형태면 True.
    """
    from urllib.parse import urlparse
    p = urlparse(url)
    base_dir = p.path.rsplit("/", 1)[0]
    for lu in confirmed_list_urls:
        lp = urlparse(lu)
        if lp.netloc != p.netloc:
            continue
        if base_dir == lp.path.rsplit("/", 1)[0]:
            if "pageNo=" in (p.query or "") or "view.do" in p.path.lower():
                return True
    return False
```
`enqueue_seeds` 본문에서 도메인의 confirmed list_url 집합을 1회 로드:
```python
    async with session_factory() as s:
        confirmed_list_urls = set((await s.execute(
            select(BoardSource.list_url).where(
                BoardSource.domain_id == domain_id, BoardSource.status == "confirmed",
            )
        )).scalars().all())
```
그리고 discovered 링크를 frontier에 넣기 전에 `if is_board_owned_link(u, confirmed_list_urls=confirmed_list_urls): continue` 필터 추가. import에 `BoardSource`, `select` 확인.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_full_board_exclusion.py -v`
Expected: PASS

- [ ] **Step 5: 회귀 확인**

Run: `python -m pytest tests/ -k "enqueue_seeds or full" -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add src/kspo_ingest/tasks/pipeline/enqueue_seeds.py tests/test_full_board_exclusion.py
git commit -m "feat(pipeline): 월간 full에서 confirmed board 하위 링크 제외"
```

---

### Task 11: `board_sources` API 라우터 + 스키마

**Files:**
- Create: `src/kspo_ingest/api/schemas/board_source.py`
- Create: `src/kspo_ingest/api/routers/board_sources.py`
- Modify: `src/kspo_ingest/api/main.py` (라우터 등록)
- Test: `tests/test_api_board_sources.py`

**Interfaces:**
- Consumes: `BoardSource` (Task 1), `AdminDep`/`SessionDep` (`api/deps.py`).
- Produces: `GET /api/board-sources?status=`, `POST /api/board-sources`(수동추가→confirmed), `POST /api/board-sources/{id}/confirm`, `POST /api/board-sources/{id}/reject`, `DELETE /api/board-sources/{id}`.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_api_board_sources.py`:
```python
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_list_requires_auth(async_client):
    resp = await async_client.get("/api/board-sources")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_confirm_transitions_status(async_client, admin_auth, seed_candidate_source):
    src_id = seed_candidate_source
    resp = await async_client.post(f"/api/board-sources/{src_id}/confirm", headers=admin_auth)
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"
```
(fixtures `async_client`, `admin_auth`는 기존 API 테스트 파일 — 예: `tests/test_api_domains.py` — 에서 쓰는 것을 재사용. `seed_candidate_source`는 candidate BoardSource 1건 생성 후 id 반환하는 로컬 fixture로 이 파일에 정의.)

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_api_board_sources.py -v`
Expected: FAIL (404 — 라우터 미등록)

- [ ] **Step 3: 스키마 구현**

`src/kspo_ingest/api/schemas/board_source.py`:
```python
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
    newest_first: bool
    detected_at: datetime
    confirmed_at: datetime | None
    last_refreshed_at: datetime | None
```

- [ ] **Step 4: 라우터 구현**

`src/kspo_ingest/api/routers/board_sources.py`:
```python
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.api.deps import AdminDep, SessionDep
from kspo_ingest.api.schemas.board_source import BoardSourceCreate, BoardSourceOut
from kspo_ingest.db.models import BoardSource

router = APIRouter(prefix="/api/board-sources", tags=["board-sources"])


@router.get("", response_model=list[BoardSourceOut])
async def list_sources(status: str | None = None, s: AsyncSession = SessionDep, _a: str = AdminDep):
    q = select(BoardSource)
    if status:
        q = q.where(BoardSource.status == status)
    q = q.order_by(BoardSource.status, BoardSource.detected_at.desc())
    return list((await s.execute(q)).scalars().all())


@router.post("", response_model=BoardSourceOut, status_code=status.HTTP_201_CREATED)
async def add_source(body: BoardSourceCreate, s: AsyncSession = SessionDep, _a: str = AdminDep):
    src = BoardSource(domain_id=body.domain_id, list_url=body.list_url,
                      status="confirmed", confirmed_at=datetime.now(UTC))
    s.add(src)
    await s.commit()
    await s.refresh(src)
    return src


async def _get(s: AsyncSession, id: int) -> BoardSource:
    src = await s.get(BoardSource, id)
    if src is None:
        raise HTTPException(status_code=404, detail="not found")
    return src


@router.post("/{id}/confirm", response_model=BoardSourceOut)
async def confirm(id: int, s: AsyncSession = SessionDep, _a: str = AdminDep):
    src = await _get(s, id)
    src.status = "confirmed"
    src.confirmed_at = datetime.now(UTC)
    await s.commit()
    await s.refresh(src)
    return src


@router.post("/{id}/reject", response_model=BoardSourceOut)
async def reject(id: int, s: AsyncSession = SessionDep, _a: str = AdminDep):
    src = await _get(s, id)
    src.status = "rejected"
    await s.commit()
    await s.refresh(src)
    return src


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(id: int, s: AsyncSession = SessionDep, _a: str = AdminDep):
    src = await _get(s, id)
    await s.delete(src)
    await s.commit()
```

- [ ] **Step 5: main.py 등록**

`src/kspo_ingest/api/main.py` — import + `app.include_router(board_sources.router)` 추가(다른 AdminDep 라우터 옆).

- [ ] **Step 6: 통과 확인**

Run: `python -m pytest tests/test_api_board_sources.py -v`
Expected: PASS

- [ ] **Step 7: 커밋**

```bash
git add src/kspo_ingest/api/schemas/board_source.py src/kspo_ingest/api/routers/board_sources.py src/kspo_ingest/api/main.py tests/test_api_board_sources.py
git commit -m "feat(api): board-sources 라우터 (list/add/confirm/reject/delete)"
```

---

### Task 12: 관리자 UI — 게시판 소스 화면

**Files:**
- Create: `web/api/boardSources.ts` (React Query 훅)
- Create: `web/app/(authed)/board-sources/page.tsx`
- Modify: `web/components/AppShell.tsx` (nav 항목 + candidate count 뱃지)
- Modify: `web/app/(authed)/domains/[id]/page.tsx` (해당 도메인 board_source 목록 읽기 섹션)

**Interfaces:**
- Consumes: `apiFetch` (`web/lib/api.ts`), Task 11 엔드포인트.
- Produces: `useBoardSources(status?)`, `useConfirmSource()`, `useRejectSource()`, `useAddSource()`, `useDeleteSource()`.

> UI는 프로젝트 규약상 단위 테스트 없음 — lint + `tsc` + 수동 검증. 디자인 시스템 토큰·기존 컴포넌트(`Table`/`Badge`/`Button`/`ConfirmDialog`/`Input`)만 사용.

- [ ] **Step 1: React Query 훅 작성**

`web/api/boardSources.ts` — 기존 `web/api/domains.ts` 패턴을 그대로 따른다:
```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '@/lib/api'

export type BoardSource = {
  id: number; domain_id: number; list_url: string; status: string
  newest_first: boolean; detected_at: string
  confirmed_at: string | null; last_refreshed_at: string | null
}

export function useBoardSources(status?: string) {
  return useQuery({
    queryKey: ['board-sources', status ?? 'all'],
    queryFn: () => apiFetch<BoardSource[]>(`/api/board-sources${status ? `?status=${status}` : ''}`),
  })
}

function useAction(path: (id: number) => string, method = 'POST') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => apiFetch(path(id), { method }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['board-sources'] }),
  })
}

export const useConfirmSource = () => useAction((id) => `/api/board-sources/${id}/confirm`)
export const useRejectSource = () => useAction((id) => `/api/board-sources/${id}/reject`)
export const useDeleteSource = () => useAction((id) => `/api/board-sources/${id}`, 'DELETE')

export function useAddSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { domain_id: number; list_url: string }) =>
      apiFetch('/api/board-sources', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['board-sources'] }),
  })
}
```

- [ ] **Step 2: 화면 작성**

`web/app/(authed)/board-sources/page.tsx` — `AppShell` 안에 표(도메인/list_url/status 뱃지/탐지일/마지막 갱신 + 승인·거부·삭제 액션) + 상단 수동 추가 폼(domain_id, list_url). 거부/삭제는 `ConfirmDialog`. `useBoardSources('candidate')` 우선 노출. (기존 `domains/page.tsx` 레이아웃을 참고해 동일 컴포넌트로 구성.)

- [ ] **Step 3: nav 항목 + count 뱃지**

`web/components/AppShell.tsx` — nav 배열에 `{ href: '/board-sources', label: '게시판 소스', icon: <아이콘>, count: candidateCount }` 추가. `candidateCount`는 `useBoardSources('candidate').data?.length`. 기존 미사용 `NavItem.count` 필드로 뱃지 렌더.

- [ ] **Step 4: 도메인 상세에 board_source 섹션**

`web/app/(authed)/domains/[id]/page.tsx` — 하단에 `useBoardSources()`에서 `domain_id === id` 필터한 목록(읽기 전용 표) 추가.

- [ ] **Step 5: lint + 타입체크**

Run: `cd web && npm run lint && npx tsc --noEmit`
Expected: 오류 없음

- [ ] **Step 6: 커밋**

```bash
git add web/api/boardSources.ts web/app/\(authed\)/board-sources/ web/components/AppShell.tsx web/app/\(authed\)/domains/
git commit -m "feat(web): 게시판 소스 관리 화면 (후보 확인/승인/수동추가)"
```

---

### Task 13: 전체 회귀 + 통합 스모크

**Files:**
- Test: 전체 스위트

- [ ] **Step 1: 전체 백엔드 스위트**

Run: `python -m pytest -q`
Expected: 신규 테스트 포함 통과, 기존 pre-existing 실패(auth greenlet 등) 외 회귀 없음.

- [ ] **Step 2: 마이그레이션 왕복 확인 (테스트 DB)**

Run: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
Expected: 오류 없음(0007 up/down 정상).

- [ ] **Step 3: cron 개수 로그 정합 확인**

`tasks/worker.py`의 `on_startup` cron_count 로그가 실제 등록 cron 수(monthly_full_all, daily_board_refresh, archive_expired_board_posts, archive_expired_documents, refresh_stats_views, cron_kpi_daily, check_budget_alerts = 7)와 일치하는지 확인.

- [ ] **Step 4: 커밋 (필요 시 로그 수정)**

```bash
git add -A && git commit -m "chore: 게시판 재설계 전체 회귀 + cron_count 정합" || echo "no changes"
```

---

## Self-Review 결과

- **Spec coverage**: 섹션1(Task1) · 섹션2 자동탐지(Task2,3) · 섹션3 일간크롤(Task5,6,7) · 섹션4 아카이브(Task4,8) · 섹션5 월간full+주간제거(Task9) + full제외(Task10) · 섹션6 API/UI(Task11,12). 전 섹션 매핑됨.
- **Placeholder scan**: 코드 블록은 실제 구현. 단, 두 곳은 "기존 파일의 지역 변수/ctx 키에 맞춘다"고 명시 — extract_links의 html 변수명(Task3 S5)과 worker on_startup의 fetcher ctx 키(Task6 S4). 구현 시 해당 파일 확인 필요(계획 실패 아님, 통합 지점 특성).
- **Type consistency**: `BoardSource` 필드·`move_points(from_col,to_col,point_ids)->int`·`get_or_create_page(...,board_source_id,posted_at)`·`classify_board_list->BoardSignal`·`build_page_url`·`is_board_owned_link(...,confirmed_list_urls=)` 전 태스크에서 이름 일치.
- **알려진 통합 리스크**: Task1~7은 순차 브랜치에서 진행(중간에 is_board 참조로 스위트가 잠시 깨질 수 있음 — Task7 후 전체 그린). Task6의 fetcher는 worker ctx 실제 키 확인 필수.
