# 04. 증분 / API / Admin UI

## 4.1 Job 종류 — 3개로 단순화

| Job | 트리거 | 처리 단위 |
|---|---|---|
| `full` | 도메인 첫 등록 / 수동 | 도메인 전체 BFS |
| `incremental` | 주 1회 일요일 03:00 KST cron / 수동 | 도메인 전체 + content_hash 비교 |
| `url_refresh` | Admin 단건 강제 | 1 URL |

> v1.0 대비 빠진 종류: `board_refresh`/`since_refresh`/`backfill_*`(3종)/`cleanup_orphans` — 모두 Tier 2.
> 게시판 신선도 갱신은 `incremental`(주 1회)로 충족된다는 가정. 실측 후 부족하면 Tier 2에서 `board_refresh` 추가.

## 4.2 crawl_jobs 테이블

```sql
CREATE TABLE crawl_jobs (
  id BIGSERIAL PRIMARY KEY,
  domain_id BIGINT NOT NULL REFERENCES domains(id),
  job_type TEXT NOT NULL,             -- full | incremental | url_refresh
  seed_urls TEXT[],
  status TEXT NOT NULL,                -- PENDING|RUNNING|SUCCESS|FAILED|CANCELLED
  triggered_by TEXT NOT NULL DEFAULT 'admin',
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  stats JSONB,                         -- {discovered,fetched,skipped,refined,indexed,errors,cost_usd}
  error_message TEXT,
  arq_job_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_jobs_status ON crawl_jobs(status);
CREATE INDEX idx_jobs_domain ON crawl_jobs(domain_id);
```

## 4.3 변경 감지 흐름

```
1) Crawler URL 재방문 → 새 raw HTML (영구 보관, 버전 적재)
2) Cleaner: 본문 추출 → content_hash 계산
3) PG pages.content_hash 비교
   - 동일: skip(LLM·임베딩 비용 0), last_fetched_at만 갱신
   - 다름: refine → chunk → embed → Qdrant upsert + diff 동기화
4) pages.last_indexed_at, content_hash 갱신
```

## 4.4 Orphan 처리 (단순화)

- 연속 3회 404 → `pages.status='REMOVED'` + KB chunks 삭제
- `is_meaningful` false 전환 → 기존 chunks 삭제 + DROPPED
- 도메인 비활성화(`is_active=false`) → Direct 어댑터의 `delete_by_domain('host')` 호출 후 PG `pages.status='REMOVED'` 일괄

> 정기 cleanup_orphans Job 미운영. PG↔Qdrant 차이가 운영상 문제로 드러나면 Tier 2에서 추가.

## 4.5 API 카탈로그 (14개)

### 도메인 (5)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/domains` | 목록 |
| POST | `/api/domains` | 등록 |
| GET | `/api/domains/{id}` | 조회 |
| PATCH | `/api/domains/{id}` | 수정 |
| DELETE | `/api/domains/{id}` | 삭제(연관 chunks·KB 삭제) |

### Job (6)

| Method | Path | 설명 |
|---|---|---|
| POST | `/api/jobs/full/{domain_id}` | 전체 크롤 |
| POST | `/api/jobs/incremental/{domain_id}` | 변경분 크롤 |
| POST | `/api/jobs/refresh-url` | `{url, force?}` 단건 |
| GET | `/api/jobs` | 필터 목록 |
| GET | `/api/jobs/{id}` | 상세 + stats |
| POST | `/api/jobs/{id}/cancel` | 취소 |

### 페이지·첨부·헬스 (3)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/pages?domain_id=&q=&status=` | 검색 |
| GET | `/api/pages/{id}` | 상세 (raw/cleaned/refined 미리보기) |
| GET | `/files/{attachment_id}` | 공개 다운로드(인증 없음) |

### 헬스 / OpenAPI (자동)

| Method | Path | 설명 |
|---|---|---|
| GET | `/healthz` | 라이브니스 |
| GET | `/readyz` | PG/Redis/Qdrant 차원 체크 |
| GET | `/docs` `/openapi.json` | Swagger |

> v1.0의 첨부 메타 API/카테고리/오버라이드/보일러플레이트/통계/감사 로그/DLQ/SSE/`/resolve/attachments` 모두 제거.

## 4.6 인증

| 주체 | 방식 | 범위 |
|---|---|---|
| Admin | Basic Auth → 세션 (bcrypt cost ≥ 12) | `/api/*`, `/` UI |
| 외부 사용자 | 없음 | `/files/{id}`, `/healthz` |

> v1.0의 Internal Token / Search Bearer 제거. 챗봇이 본 시스템을 호출하지 않으므로 불필요.

## 4.7 Admin UI — 5페이지 (React SPA)

### 4.7.0 기술 스택

- React 18+ / TypeScript
- Tailwind CSS (`design-system/tokens/tailwind.config.js`)
- shadcn/ui (Radix 기반) + lucide-react 아이콘
- 데이터 페칭: TanStack Query (React Query) — 폴링 간격은 `refetchInterval`로 제어
- 라우팅: React Router (또는 TanStack Router)
- 빌드: Vite

> 시각 어휘는 `design-system/` 단일 진실원. 토큰·컴포넌트 변형 시 `design-system/CLAUDE.md` 절대 금지 사항 준수.

### 4.7.1 사이트맵

```
/             대시보드
/login        로그인 폼 (Basic Auth → 세션 쿠키)
/domains      목록 (List → Detail) — `/domains/new`, `/domains/:id`
/jobs         목록 — `/jobs/:id` (refetchInterval 5000ms)
/pages        검색 (서버 페이지네이션)
/settings     환경변수 미러 + 비밀번호 변경
```

> v1.0의 `/jobs/dead`, `/categories`, `/overrides`, `/domains/*/boilerplate`, `/stats(차트)`, `/audit-log` 제거. SSE 미사용 — React Query 폴링.

### 4.7.2 페이지 골격

모든 페이지는 `design-system/examples/AppShell.tsx` 의 골격을 따른다:
Sidebar(248px) + Topbar(56px, breadcrumbs+actions) + Page header(h1+subtitle) + Content(max-width 1280).

### 4.7.3 대시보드 카드

- 활성 Job (진행률 바)
- 오늘/이번 주/이번 달 LLM 비용
- 도메인별 페이지 수 (간단 표)
- KB 헬스 (Qdrant 차원, 컬렉션 포인트 수)
- 최근 에러 5건

각 카드는 React Query `refetchInterval: 30000` 으로 자동 갱신. KPI 카드는 `design-system/PATTERNS.md` 패턴 4 참조.

### 4.7.4 도메인 등록 폼

필드: host, scheme, display_name / max_depth, max_pages, rate_limit_rps, concurrency / use_playwright, respect_robots, user_agent / allow_patterns, deny_patterns / selector_blacklist (textarea) / incremental_cron, incremental_enabled.

폼은 `design-system/COMPONENTS.md` Input/Form 규칙 준수 (height 36, radius 8, focus halo 3px). 저장 후 즉시 `full` Job 자동 enqueue 옵션(체크박스).

### 4.7.5 Job 상세

- 상단: 상태(`StatusPill`), 시작/종료, 진행률 바, 비용 합계
- 통계: discovered/fetched/skipped/refined/indexed/errors (테이블, `tabular-nums`)
- 액션: Cancel(destructive 확인 모달), Retry-failed
- React Query `refetchInterval: 5000`. 종료 상태(`SUCCESS|FAILED|CANCELLED`)에 진입하면 폴링 중단.

`StatusPill` 변형은 `design-system/examples/StatusPill.tsx` 의 5종(running/success/failed/paused/pending) 그대로 사용.

### 4.7.6 페이지 상세 (Tabbed Detail 패턴)

탭(`design-system/PATTERNS.md` 패턴 5):
- 메타: URL, status, hash, posted_at, last_indexed_at
- raw HTML(rendered iframe — sandbox)
- cleaned text
- refined JSON (코드 블록, Geist Mono)
- chunks (텍스트·KB id·임베딩 모델 — 테이블)
- attachments (카드 + 다운로드 링크)

액션: Force Refresh (`POST /api/jobs/refresh-url`).

### 4.7.7 빌드/배포

- 정적 산출물(`dist/`)을 FastAPI `StaticFiles` 로 마운트하거나 nginx 별도 컨테이너로 배포
- 개발 시 Vite dev server(5173) → FastAPI(8080) 프록시 (`/api/*`, `/files/*`)
- 라우팅은 SPA fallback (모든 비-API 경로는 `index.html` 반환)

> 프런트엔드 패키지(`package.json`, Vite 설정 등)는 별도 Task에서 스캐폴딩. 본 절은 설계 결정만 명시.

## 4.8 부팅 라이프사이클

```python
@app.on_event('startup')
async def startup():
    await db.engine_init()
    await alembic_check_revisions()        # 미반영 시 503
    await ensure_qdrant_collection()       # KB_BOOTSTRAP=managed면 차원 검증
    await arq_pool_init()
    await scheduler.warm()                 # ARQ cron (주간 incremental)
    log.info("api_ready")
```

`ALEMBIC_AUTO=true`(개발) 시 자동 upgrade. 운영은 `docker compose --profile migrations run --rm migrations` 1회.

## 4.9 미들웨어

- `X-Request-Id` 부여 + contextvars
- Body 1MB 상한
- `/api/jobs/refresh-url` 분당 60회 레이트리밋
- 에러 포맷: `{"error":{"code","message","request_id"}}`
- Pydantic ValidationError → 422
