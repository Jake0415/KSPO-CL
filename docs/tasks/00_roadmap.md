# 로드맵 — KSPO 적재 시스템 v2.1

> 작성: 2026-05-07
> 출처: PRD [docs/prd/00_index.md](../prd/00_index.md) v1.4 (7파일 분리) + design docs v2.1
> 다음: M0 Task 파일 작성 → M0.T0.1 코드 진입

---

## 0. 개요

- 본 시스템 = lite v2.0 docx + PRD round 1·2 결정 = **v2.1**
- **6 마일스톤 (PoC → M0 ~ M5) → 파일럿 → 정식 전환**
- **총 24 Task** (M0=4 + M1=5 + M2=4 + M3=4 + M4=3 + M5=4; PoC는 별도 단계)
- **개발 기간 추정**: 3~4주 (PRD §8.1 — KSPO 사업관리 deadline)

---

## 1. 단계 의존성

```
[PoC] P1~P4 (Tiledesk Qdrant payload·차원·upsert·검색 검증, 1~2일)
   │  ※ poc/report.md 산출
   ▼
[M0] 부트스트랩 (4 Task, ~Week 1)
   │
   ▼
[M1] 데이터 모델 + Admin 골격 (5 Task, ~Week 2)
   │
   ▼
[M2] Crawl + Clean + Refine (4 Task, ~Week 2~3)
   │
   ▼
[M3] Embed + Qdrant Direct + 첨부 (4 Task, ~Week 3)
   │
   ▼
[M4] Incremental + Refresh + Cron (3 Task, ~Week 4)
   │
   ▼
[M5] 운영 + 인계 (4 Task, ~Week 4)
   │
   ▼
[파일럿] 2~4주, KSPO 본사이트 1 도메인
   │
   ▼
[정식 전환] Qdrant 듀얼모드 → Tiledesk 외부, PoC P1~P4 재검증
```

---

## 2. 작업 단위 정책

(`CLAUDE.md` 작업 단위 규약 미러)

- **1 PR ≈ 1 Task** = `docs/tasks/M{n}_T{n.m}.md` 파일 하나
- PR 본문: `Closes` / `Summary` / `Test` / `Risk`
- Alembic 마이그레이션 추가 시 revision id 명시
- 새 환경변수 추가 시 `.env.example` 갱신
- 외부 의존성 추가는 `pyproject.toml` 한 곳만
- 신규 모듈은 단위 테스트 동반 (>80% 커버리지)

---

## 3. 마일스톤 상세

### 3.1 PoC — 별도 단계

| # | 검증 항목 | 산출물 | 결정 시점 |
|---|---|---|---|
| P1 | Tiledesk Qdrant payload 키 캡처 | `poc/captures/P1_payload.json` | 1일차 |
| P2 | 차원 호환성 (text-embedding-3-large 3072) | `poc/captures/P2_dims.json` | 1일차 |
| P3 | Upsert + Delete 동작 | `poc/captures/P3_upsert.txt` | 1일차 |
| P4 | E2E 검색 (`/api/qa`) | `poc/captures/P4_search.json` | 2일차 |

**산출물 종합**: `poc/report.md` 1장 — payload 키 컨벤션, 차원, upsert·delete 결정, e2e 검증.
**진입 조건**: Tiledesk Compose 가동 (별도 호스트 또는 동일 호스트 docker network 공유).

> 파일럿까지는 자체 Qdrant 컨테이너로 진행하므로 PoC를 미리 못 해도 M0~M4 진행 가능. 단 정식 운영 전환 직전에 P1~P4 **재검증 의무** (PRD §4.2).

---

### 3.2 M0 부트스트랩 (4 Task, ~Week 1)

| Task | 제목 | 핵심 산출물 | v2.1 변경 사항 |
|---|---|---|---|
| **M0.T0.1** | FastAPI 최소 골격 | `src/kspo_ingest/{settings,observability/logger,db/engine,api/main,api/middleware,api/routers/health}.py` + tests | proxy 환경변수(`HTTPS_PROXY`/`NO_PROXY`) 검증 + `OPENAI_MONTHLY_BUDGET_KRW` 추가 |
| **M0.T0.2** | Docker + Compose + Alembic | `docker/{Dockerfile.api,Dockerfile.worker,Dockerfile.migrations,Dockerfile.web,nginx/nginx.conf}` + `docker-compose.yml` + `alembic.ini` + `migrations/0001_init.py` | 6 services (nginx + qdrant 추가), Dockerfile.web (Node 20 + nginx multi-stage), TZ=Asia/Seoul |
| **M0.T0.3** | CI + 운영 문서 | `.github/workflows/ci.yml` + `PULL_REQUEST_TEMPLATE.md` + `CONTRIBUTING.md` + `docs/runbook/A,B,C` (B는 B.2.A/B.2.B 분기) | 런북 B 분기 반영 |
| **M0.T0.4** ⭐ | Frontend bootstrap | `web/{package.json,vite.config.ts,tailwind.config.js,src/}` + AppShell + 5 routes 스텁 + design-system 통합 | **신규** — design-system 토큰 적용, nginx에서 SPA serve |

**M0 종료 기준**:
- `docker compose up -d` 후 모든 서비스 healthy
- `curl http://localhost/` → SPA 로딩
- `curl http://localhost/api/healthz` → 200
- CI 5분 내 통과

---

### 3.3 M1 데이터 모델 + Admin 골격 (5 Task, ~Week 2)

| Task | 제목 | 핵심 산출물 |
|---|---|---|
| **M1.T1.1** | Alembic 마이그레이션 — 6 테이블 | `migrations/0002_core_tables.py` (domains/crawl_jobs/pages/attachments/chunks/llm_usage) — `_appendix.md` §A 미러 |
| **M1.T1.2** | SQLAlchemy 모델 + 검증 | `src/kspo_ingest/db/models.py` + 단위 테스트 (CRUD round-trip) |
| **M1.T1.3** | 도메인 CRUD API | `/api/domains` 5 endpoints + Pydantic 스키마 + respx 테스트 |
| **M1.T1.4** | Admin 인증 | HTTP Basic Auth → 세션 쿠키 (bcrypt cost ≥ 12) + 세션 8h 만료 + middleware |
| **M1.T1.5** | Admin React UI 도메인 페이지 | `web/src/pages/domains/` (List + New + Detail), design-system 컴포넌트 (`btn`/`card`/`table`/`input`) |

**M1 종료 기준**:
- Admin 로그인 후 도메인 등록·수정·삭제 UI에서 동작
- `pytest -k m1` all green

---

### 3.4 M2 Crawl + Clean + Refine (4 Task, ~Week 2~3)

| Task | 제목 | 핵심 산출물 |
|---|---|---|
| **M2.T2.1** | Crawler | httpx HTTP/2 + URL 정규화 (utm_*, fbclid, gclid 제거 / `bbsId`,`nttId` 보존) + Redis frontier + robots.txt + tenacity 재시도 |
| **M2.T2.2** | Cleaner | `<main>`/`<article>` → Trafilatura → Readability → 휴리스틱 + Selector blacklist + 인코딩 탐지 + `normalize_for_hash` |
| **M2.T2.3** | Refiner | OpenAI structured output (4 fields: refined_text/is_meaningful/summary/keywords) + 사전 룰 (too_short/error_page/non_korean) + `llm_usage` 기록 |
| **M2.T2.4** | ARQ Job 관리 | `enqueue_seeds`/`fetch_page`/`clean_page`/`refine_page` 체인 + Job stats(JSONB) + `crawl_jobs` 라이프사이클 |

**M2 종료 기준**:
- KSPO 본사이트 1 페이지 → DISCOVERED → REFINED → DROPPED 또는 미INDEXED
- 사전 룰 3종 동작 (too_short/error_page/non_korean DROPPED)
- `llm_usage` 행 생성

---

### 3.5 M3 Embed + Qdrant + 첨부 (4 Task, ~Week 3)

| Task | 제목 | 핵심 산출물 |
|---|---|---|
| **M3.T3.1** | Chunker | 2단 청킹 (>800 → window_split / 그 외 단일) + 컨텍스트 헤더 1종 + 첨부 청크 헤더 |
| **M3.T3.2** | Embedder | text-embedding-3-large 배치 (input 96 청크) + 부분 실패 fallback + 비용 추적 |
| **M3.T3.3** ⭐ | Qdrant Direct Adapter | `ensure_collection` / `upsert_chunks` / `delete_by_ids` / `delete_by_domain` / `replace_page_chunks`. **듀얼 모드 동작 — `QDRANT_URL` 토글로 자체 ↔ Tiledesk 전환** |
| **M3.T3.4** | 첨부 다운로드·추출 | pypdf/python-docx/openpyxl/python-pptx + 100MB 상한 + `/files/{id}` 공개 엔드포인트 + HWP는 `extraction_status='SKIPPED'` |

**M3 종료 기준**:
- KSPO 본사이트 1 페이지 INDEXED 도달
- 자체 Qdrant 컨테이너에 청크 적재 확인 (대시보드 또는 `qdrant-client`)
- `chunks.kb_status='OK'`

---

### 3.6 M4 Incremental + Refresh (3 Task, ~Week 4)

| Task | 제목 | 핵심 산출물 |
|---|---|---|
| **M4.T4.1** | Incremental Job | `run_incremental` (content_hash 비교, 미변경 skip / 변경 refine→chunk→embed→Qdrant diff 동기화) |
| **M4.T4.2** | URL Refresh + Job 관리 | `POST /api/jobs/refresh-url` + `POST /api/jobs/{id}/cancel` + 분당 60회 레이트리밋 |
| **M4.T4.3** | 주간 cron + 통계 뷰 | `weekly_incremental_all` (일요일 03:00 KST) + `refresh_stats_views` (5분 주기) |

> **시간대 안전망**: PRD §5.1 정기 재시작 윈도우(매월 둘째 일요일 02:00 KST)는 weekly cron 시작(03:00) 1시간 전에 종료되어야 한다. 재시작 지연 시 cron 누락 위험 — KSPO IT 보안 패치 일정과 동기화 시 30분 buffer 확보 권장.

**M4 종료 기준**:
- 1 도메인 incremental 실행 → 변경 페이지만 재처리
- v_stats_overview·v_cost_daily 뷰 갱신 동작

---

### 3.7 M5 운영 + 인계 (4 Task, ~Week 4)

| Task | 제목 | 핵심 산출물 |
|---|---|---|
| **M5.T5.1** | 로깅·비용 모니터링 | loguru JSON 마스킹 정착 + 월 LLM 누계 80% 도달 알림 (`OPENAI_MONTHLY_BUDGET_KRW × 0.8`) + UI 배너 + 이메일 |
| **M5.T5.2** | 통합·E2E 테스트 | `docker-compose.test.yml` + qdrant stub + e2e 1 도메인 시나리오 + KPI 측정 스크립트 |
| **M5.T5.3** | 운영 매뉴얼 PDF + 교육 | `docs/runbook/A,B,C` + `docs/operations/` → **PDF 가공** + **교육 슬라이드 1 세트** (Admin·KSPO IT 대상) |
| **M5.T5.4** | KPI 측정·파일럿 보고서 | KPI 4종 (커버리지·신선도·Job 성공률·월 비용) 자동 측정 + 파일럿 보고서 템플릿 (`docs/reports/pilot_template.md`) |

**M5 종료 기준**:
- 모든 런북 PDF 출력 가능
- KPI 측정 자동화
- 무한아이티 → KSPO 인수 시점 (PRD §2.1)

---

### 3.8 파일럿 + 정식 전환 (Task 미생성 — 운영 단계)

**파일럿** (2~4주, PRD §8.2):
- 대상: KSPO 본사이트(`www.kspo.or.kr`) 1 도메인
- 측정: 적재 커버리지·Job 성공률·월 LLM 비용·검색 품질(Tiledesk 협조)
- 종료 조건: KPI 권장 목표 80% 이상 + KSPO Admin 교육 완료 + KSPO IT 인수 합의

**정식 전환** (PRD §4.2 — 파일럿 종료 후):
1. Tiledesk 측 `index_name`·차원·payload 키 컨벤션 확보
2. `.env`의 `QDRANT_URL`을 Tiledesk 외부 인스턴스로 변경
3. PoC P1~P4 재검증 의무
4. 검증 통과 시 자체 `qdrant` 서비스·볼륨 삭제 → 5 services
5. `full` Job 재실행으로 Tiledesk 컬렉션 채우기

---

## 4. 외부 의존성 게이트

| 의존성 | 필요 시점 | 미해결 시 영향 |
|---|---|---|
| KSPO IT 호스트 사양 확정 | M0 시작 전 | 권장 최소(8 vCPU/16GB/200GB)로 시작 |
| KSPO 인프라팀 프록시 host:port | **M2 시작 전** | refine·embed 호출 불가 → M2~M3 진행 차단 |
| KSPO 인프라팀 사내 인증서 (TLS) | M0.T0.2 진입 전 | 미보유 시 self-signed로 시작, 운영 전 교체 |
| KSPO 회계 OpenAI 카드 등록 | **M2 시작 전** | refine 호출부터 비용 발생 — 카드 없으면 401/402 |
| Tiledesk Compose 가동 | PoC 시작 전 | PoC 미진행 → 정식 전환 시점에 P1~P4 재검증으로 해소 가능 |
| Tiledesk Qdrant 정보 (`index_name`·차원) | **파일럿 종료 전** | 정식 전환 차단 |

---

## 5. KPI / 산출물 게이트

| 단계 | 검증 항목 |
|---|---|
| M2 종료 | refine 작동 + 첫 페이지 status 변화 (REFINED 또는 DROPPED) + `llm_usage` 행 ≠ 0 |
| M3 종료 | 1 페이지 INDEXED + 자체 Qdrant 청크 적재 확인 |
| M4 종료 | incremental 1회 실행 — 변경 페이지만 재처리 검증 |
| M5 종료 | KPI 4종 측정값 보고서 + 운영 매뉴얼 PDF + 무한아이티 → KSPO 인계 회의 |
| 파일럿 종료 | 권장 KPI 80% 달성 + Admin 교육 완료 + KSPO 인수 합의 |
| 정식 전환 | PoC P1~P4 모두 통과 + 자체 Qdrant 컨테이너 종료 + Tiledesk 컬렉션에 1 도메인 적재 확인 |

---

## 6. PRD §9.3 외부 의사결정 일정 매핑

| PRD §9.3 | 결정 시점 | 본 로드맵 |
|---|---|---|
| #1 프록시 host:port | 운영 시작 시 | M0 시작 전 |
| #2 KPI 권장 목표 | 운영 1개월 내 | M5.T5.4 + 파일럿 |
| #3 백업 미운영 정책 | 운영 시작 전 | M0 시작 전 |
| #4 호스트 도입 방식 | M0 시작 전 | M0 시작 전 |
| #5 TLS 종료 위치 | M0.T0.2 진입 전 | M0.T0.2 |
| #6 이미지 레지스트리 | M0.T0.2 진입 전 | M0.T0.2 |
| #7 CSAP/ISMS-P | 점검 시점 | (없음 — 비대상 가정) |
| #8 개발 deadline | PRD 승인 시 | (현 추정 3~4주 유지) |
| #9 파일럿 기간·도메인 | M5 종료 시점 | M5 종료 |

---

## 7. 변경 이력

| 일자 | 버전 | 변경 |
|---|---|---|
| 2026-05-07 | v1.0 | 초안 — v2.1 기준 24 Task 로드맵 (M0 4 + M1 5 + M2 4 + M3 4 + M4 3 + M5 4 + PoC/파일럿/정식 전환은 별도 단계) |
