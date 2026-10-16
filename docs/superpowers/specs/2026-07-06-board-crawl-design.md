# 게시판 크롤링 재설계 — 목록 파싱 · 3개월 보존 · 자동 탐지

- 작성일: 2026-07-06
- 상태: 설계 승인 (구현 계획 대기)
- 관련 코드: `crawl/board.py`(죽은 코드 → 배선), `crawl/internal_links.py`, `tasks/cron.py`, `tasks/pipeline/`, `qdrant/adapter.py`, `db/models.py`, `web/`

## 배경 / 문제

현재 "게시판 크롤"은 별도 파이프라인이 아니라 `run_incremental`을 재사용한다. 구분은 `Domain.is_board` 플래그 + `daily_board_refresh` cron(04:00) + `triggered_by='cron_board'` 태그뿐이며, 실제 게시판 특화 로직(목록 파싱, 3개월 컷오프, 텍스트만)은 파이프라인에 배선되어 있지 않다. `crawl/board.py`(`extract_board_items`, `is_within_freshness`)는 커밋 `d277672`(2026-07-04)에 유닛+테스트만 추가된 뒤 한 번도 `src/`에서 import된 적 없는 죽은 코드다.

요구사항(확정):

- **전체(full) 크롤**: 월 1회.
- **게시판 크롤**: 일 1회, **최근 3개월 데이터만 보존**, 목록 페이지 URL 기반 **목록 파싱**.
- 만료(3개월 경과) 게시글: **`kspo_archive` 컬렉션으로 이동**(삭제 아님).
- 게시판은 **월간 full 대상에서 제외**.
- 게시판 목록 URL 등록: **자동 탐지 + 관리자 확인(하이브리드)**, 수동 등록도 가능.

## 설계 전제: 게시판은 "URL 단위"

한 도메인은 일반 페이지 + 여러 게시판을 동시에 가진다. `is_board`(도메인 전체 플래그)는 부정확하므로 **게시판 목록 URL을 도메인 하위 개별 레코드(`board_source`)로** 관리한다. 이러면 "월간 full 제외"도 "확인된 board_source의 목록·상세 URL만 제외, 나머지 일반 페이지는 정상 full"로 정확히 표현된다.

## 채택 접근 (대안 대비)

- **A. 전용 board 태스크 `run_board_refresh` (채택)** — board.py를 배선하고 per-page 파이프라인을 재사용. 단일 책임 분리.
- B. `run_incremental`에 `is_board` 분기 — 핵심 파이프라인을 이중 목적으로 오염, 테스트/유지보수 악화. 기각.
- C. 설정만(기존 BFS + retention cron만) — 3개월 페이지네이션 중단 없음 → 매일 게시판 전체 재크롤(비용↑), posted_at 상세 추출 의존(불안정), "목록 파싱" 요구 불충족. 기각.

---

## 섹션 1 — 데이터 모델 & 설정

### 신규 테이블 `board_source` (Alembic revision 0007)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | BigInt PK | |
| `domain_id` | FK → domains, ON DELETE CASCADE | 소속 도메인 |
| `list_url` | Text | 게시판 목록 페이지 URL (페이지네이션 시작점) |
| `status` | Text | `candidate` / `confirmed` / `rejected` |
| `newest_first` | Bool, default true | 목록 정렬이 최신순인가 (페이지네이션 조기 중단 판정용) |
| `detected_at` | timestamptz, default now() | 자동 탐지 시각 |
| `confirmed_at` | timestamptz null | 승인 시각 |
| `last_refreshed_at` | timestamptz null | 마지막 일간 크롤 시각 |
| UNIQUE(domain_id, list_url) | | 중복 후보 방지 |

### `Page` 모델 변경

- `board_source_id`: FK → board_source, nullable 추가. 게시글이면 세팅.
- `posted_at`(기존 컬럼) 활용 — 아카이브 retention 기준.

### `Domain.is_board` 제거(deprecate)

- 마이그레이션에서 기존 `is_board=true` 도메인이 있으면 그 도메인 루트 URL을 `board_source(status='candidate')`로 이관.
- `Domain.is_board` 컬럼 및 참조(`cron.py`, `worker.py` 주석) 정리.

### 설정

- `settings.board_freshness_days = 90`(기존) 재활용. 신규 env 없음.

---

## 섹션 2 — 게시판 자동 탐지 (월간 full 크롤 중)

`extract_links` 단계(`extract_links.py`)에 게시판 목록 판정을 한 단계 추가. HTML이 이미 손에 있음.

### 판정 함수 `classify_board_list(html, base_url) -> BoardSignal` (`board.py` 신규, 순수 함수)

세 가지 신호를 점수화:

1. **페이지네이션 신호** — `pageNo=`/`page=` 링크 존재 (`internal_links._HREF_PAGE_RE` 재활용).
2. **상세글 신호** — `goView/fnView('id')` onclick 패턴 (`internal_links._GO_VIEW_RE` 재활용).
3. **날짜표 신호** — `extract_board_items()`가 날짜 있는 행 **≥5개** 반환.

**규칙: 3개 중 2개 이상 → 게시판 목록 페이지 판정** → `board_source(status='candidate')` upsert(UNIQUE로 중복 무시). 1개 이하면 일반 페이지 통과.

- 근거: 표만/페이지네이션만 있는 비게시판(1신호)을 거르고, goView 없이 `<a href>`로 상세 가는 게시판(2신호)은 잡기 위한 균형점.
- 자동 탐지는 **기존 full 로직을 바꾸지 않고 후보만 기록**한다(탐지 실패해도 full 정상). 실제 일간 크롤은 `confirmed`만 대상 → 오탐 자동 크롤 없음.

---

## 섹션 3 — 일간 board 크롤 태스크 `run_board_refresh`

신규 ARQ 태스크 `tasks/pipeline/run_board_refresh.py`. 일간 cron(04:00)이 `is_active` 도메인마다 enqueue(현재 `daily_board_refresh → run_incremental` 배선을 이걸로 교체). `CrawlJob(job_type="board", triggered_by="cron_board")`.

```
cutoff = now - board_freshness_days(90)
for src in 해당 도메인의 confirmed board_source:
    page_no = 1
    while page_no <= MAX_BOARD_PAGES(가드, 예: 200):
        html  = fetch(build_page_url(src.list_url, page_no))    # pageNo 파라미터 부착
        items = extract_board_items(html)                        # [(detail_url, posted_at)] (공지행 제외)
        if not items: break                                      # 게시판 끝
        in_window = [it for it in items if it.posted_at >= cutoff]
        for it in in_window:
            page = get_or_create_page(it.detail_url,
                       board_source_id=src.id, posted_at=it.posted_at)
            fetch_page → clean_page(hash skip) → refine_page → score → chunk_and_index
        if len(in_window) == 0 and src.newest_first: break       # 이 페이지 전부 3개월 밖 → 중단
        page_no += 1
    src.last_refreshed_at = now
finish_job(SUCCESS)
```

### 핵심 포인트

1. **posted_at을 목록 행에서 확보** → `Page.posted_at` 저장(상세 페이지 날짜 추출보다 신뢰도 높음). 아카이브 retention이 이 값에 의존.
2. **`content_hash` 스킵 재사용** — `clean_page`가 해시 동일 시 refine/chunk 생략 → 새 글·수정 글만 LLM 비용. 매일 돌아도 3개월분 전체 재임베딩 안 함.
3. **페이지네이션 중단 = 비용 통제** — "이 페이지 전부 cutoff 밖"이면 순회 중단.
4. **per-page 파이프라인 100% 재사용** — board 태스크는 "무엇을(목록)·어디까지(3개월)"만 결정.

### 엣지 케이스 방어

- **상단 고정 공지(notice)**: `extract_board_items`에 공지 행 스킵(class/아이콘 휴리스틱) 추가, 중단 판정에서 제외. 완벽 감지 어려우니 `MAX_BOARD_PAGES` 가드로 폭주 차단.
- **비-최신순 정렬**: `board_source.newest_first=false`면 조기 중단 없이 `MAX_BOARD_PAGES`까지 훑고 cutoff 필터만 적용(기본 true).

### 신규 헬퍼

- `build_page_url(list_url, page_no)` — `list_url`에 `pageNo` 파라미터를 부착/치환. `internal_links`의 페이지네이션 로직을 파라미터 직접 생성 형태로 소형 헬퍼화.

---

## 섹션 4 — 3개월 아카이브 retention (`kspo_archive`로 이동)

신규 cron `archive_expired_board_posts`(매일 05:30).

**전제**: 벡터는 PG에 없고 Qdrant에만 있음 → 재임베딩 없이 옮기려면 Qdrant에서 벡터를 읽어 재upsert.

### `QdrantDirectAdapter.move_points(from_col, to_col, point_ids)` (신규)

1. `from_col`에서 `retrieve(point_ids, with_vectors=True, with_payload=True)`.
2. `to_col('kspo_archive')`에 동일 point id로 upsert(deterministic id → 재시도 안전).
3. `from_col`에서 `delete(point_ids)`.
→ LLM/임베딩 비용 0.

### cron 흐름

```
cutoff = now - board_freshness_days(90)
pages = SELECT Page
        WHERE board_source_id IS NOT NULL
          AND posted_at < cutoff
          AND status = 'INDEXED'
for page in pages:
    point_ids = [c.qdrant_point_id for c in page.chunks if c.qdrant_point_id]
    for active_col in ['tilellm', 'kspo_knowledge']:
        adapter.move_points(active_col, 'kspo_archive', point_ids)
    mark_archived(page)          # Page.status='ARCHIVED', DocQuality 갱신
```

### 포인트

1. 기준 날짜 = `posted_at`(게시일), 크롤 날짜 아님.
2. 멱등성 — 아카이브 후 `status='ARCHIVED'`로 재선택 안 됨. `move_points`는 deterministic id upsert로 중간 실패 재시도 안전.
3. Q4(임베딩 스킵) 게시글 — point 없음 → 이동 스킵, `mark_archived`만.
4. **기존 `archive_expired_documents`와 충돌 방지** — 그 cron 쿼리에 `board_source_id IS NULL` 조건 추가(게시글 제외). 게시글은 날짜 기반 이동으로만 관리.
5. `kspo_archive`는 `ensure_all_collections`가 부팅 시 보장.
6. 되돌리기: 이동이므로 필요 시 역이동으로 복구 가능(현재 미구현, 가능성만 명시).

---

## 섹션 5 — 월간 full cron & 게시판 제외

### 신규 cron `monthly_full_all` (매월 1일 02:00)

```
for d in SELECT Domain WHERE is_active:
    (PENDING/RUNNING 잡 있으면 skip)
    CrawlJob(job_type="full", triggered_by="cron_monthly")
    enqueue_job("enqueue_seeds", job_id, domain_id)
```

ARQ cron `month=` 스펙으로 매월 1일 지정.

### 월간 full에서 게시판 제외

full BFS(`enqueue_seeds`) 순회 시:

1. **확인된 `board_source.list_url` 도달 시**: 페이지는 1회 방문하되 `pageNo≥2` 페이지네이션·`goView` 상세 링크를 frontier에 넣지 않음(게시글 본문은 daily가 소유).
2. **`board_source_id`가 세팅된 페이지**(daily 생성 게시글): full이 재수집·재임베딩하지 않고 skip.

→ 일반 페이지만 월간 full, 게시글은 일간 board로만. 중복 크롤·오래된 글 재임베딩 없음.

### 주간 incremental 제거

기존 `weekly_incremental_all`(일요일 03:00) **제거**. 요구된 두 케이던스(월간 full · 일간 board)에 정확히 맞추고 운영 단순화. 일반 페이지 신선도가 나중에 문제되면 주간 incremental 재도입(YAGNI).

### 최종 cron 세트

| Job | 시각 | 비고 |
|---|---|---|
| `monthly_full_all` | 매월 1일 02:00 | 신규. 일반 페이지 full |
| `run_board_refresh` | 매일 04:00 | 신규(daily_board_refresh 교체) |
| `archive_expired_board_posts` | 매일 05:30 | 신규 |
| `archive_expired_documents` | 매일 05:00 | 기존, `board_source_id IS NULL` 조건 추가 |
| `refresh_stats_views` | 5분마다 | 기존 유지 |
| `cron_kpi_daily` | 매일 00:30 | 기존 유지 |
| `check_budget_alerts` | 매분 | 기존 유지 |
| ~~`weekly_incremental_all`~~ | ~~일 03:00~~ | **제거** |

(worker.py의 `cron_count=5` 하드코딩 로그 문자열도 실제 개수로 수정)

---

## 섹션 6 — 관리자 API / UI (후보 확인)

### API (`api/routers/board_sources.py`, prefix `/api/board-sources`, 전부 `AdminDep`)

| Method · Path | 용도 |
|---|---|
| `GET ""` `?status=` | 목록 조회(기본 candidate 우선) |
| `POST /{id}/confirm` | `candidate → confirmed` |
| `POST /{id}/reject` | `candidate → rejected` |
| `POST ""` `{domain_id, list_url}` | 수동 추가 → 바로 `confirmed`(escape hatch) |
| `DELETE /{id}` | 삭제 |

요청/응답 Pydantic 스키마 `api/schemas/board_source.py`. `main.py`에 라우터 등록.

### UI (`web/app/(authed)/board-sources/`)

- 신규 화면 "게시판 소스" — 표: 도메인 host · `list_url` · status 뱃지 · 탐지일 · 마지막 갱신. 행 액션: 승인/거부/삭제. 상단 수동 추가 폼.
- 사이드바 nav 항목 추가(`AppShell.tsx`), candidate 개수 뱃지(미사용 `NavItem.count` 활용).
- React Query 훅 `web/api/boardSources.ts`(list/confirm/reject/add/delete + `['board-sources']` 무효화).
- 도메인 상세(`domains/[id]`)에 해당 도메인 board_source 목록(읽기) 추가.
- 디자인 시스템 토큰·기존 컴포넌트(`Table`/`Badge`/`Button`/`ConfirmDialog`) 재사용.

### 범위 밖

- 죽어있는 `useTriggerIncrementalJob`/full 수동 실행 버튼 배선은 무관 → 건드리지 않음.

---

## 테스트 전략

- 단위: `classify_board_list`(신호 조합별), `extract_board_items`(공지행 스킵·날짜 파싱), `build_page_url`, `is_within_freshness`, `move_points`(fake Qdrant).
- 파이프라인: `run_board_refresh` — 페이지네이션 중단(전부 cutoff 밖), content_hash 스킵, in-window만 처리(fakeredis + pytest-postgresql).
- retention: `archive_expired_board_posts` — 멱등성, Q4 스킵, 기존 archive cron 게시글 제외.
- full 제외: `enqueue_seeds`가 confirmed board_source 하위 링크를 frontier에 안 넣는지.
- 마이그레이션 0007: 기존 `is_board=true` → candidate 이관.
- API/UI: 라우터 인가(AdminDep), confirm/reject 상태 전이.

## 마이그레이션 & 롤아웃

1. Alembic 0007: `board_source` 생성, `Page.board_source_id` 추가, `is_board=true` 데이터 이관, `Domain.is_board` 제거.
2. 코드 배포 후 첫 월간 full → candidate 축적 → 관리자 확인 → 다음 일간 board부터 실제 크롤.
3. 백필: 필요 시 기존 게시글 페이지에 `posted_at`/`board_source_id` 백필 스크립트(선택).

## 미해결/후속(범위 밖)

- 게시판 되돌리기(archive→active) UI.
- 비-테이블(카드형) 게시판 파싱 — 현재 `<tr>` 표 기반. 실제 그런 게시판 등장 시 `extract_board_items` 확장.
- 일반 페이지 주간 신선도 필요 시 주간 incremental 재도입.
