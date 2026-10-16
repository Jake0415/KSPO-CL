# 부록

## A. 핵심 DDL 통합 (6 테이블)

본 절은 Lite v2.0의 모든 PG 테이블 DDL이다. Alembic 마이그레이션 기준.

```sql
-- 1) domains
CREATE TABLE domains (
  id BIGSERIAL PRIMARY KEY,
  host TEXT NOT NULL UNIQUE,
  scheme TEXT NOT NULL DEFAULT 'https',
  display_name TEXT,
  max_depth INTEGER NOT NULL DEFAULT 10,
  max_pages INTEGER NOT NULL DEFAULT 20000,
  rate_limit_rps NUMERIC NOT NULL DEFAULT 1.5,
  concurrency INTEGER NOT NULL DEFAULT 4,
  use_playwright BOOLEAN NOT NULL DEFAULT FALSE,
  respect_robots BOOLEAN NOT NULL DEFAULT TRUE,
  user_agent TEXT,
  allow_patterns TEXT[],
  deny_patterns TEXT[],
  selector_blacklist TEXT[],
  incremental_cron TEXT DEFAULT '0 3 * * 0',
  incremental_enabled BOOLEAN DEFAULT TRUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2) crawl_jobs
CREATE TABLE crawl_jobs (
  id BIGSERIAL PRIMARY KEY,
  domain_id BIGINT NOT NULL REFERENCES domains(id),
  job_type TEXT NOT NULL,             -- full | incremental | url_refresh
  seed_urls TEXT[],
  status TEXT NOT NULL,               -- PENDING|RUNNING|SUCCESS|FAILED|CANCELLED
  triggered_by TEXT NOT NULL DEFAULT 'admin',
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  stats JSONB,
  error_message TEXT,
  arq_job_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_jobs_status ON crawl_jobs(status);
CREATE INDEX idx_jobs_domain ON crawl_jobs(domain_id);

-- 3) pages
CREATE TABLE pages (
  id BIGSERIAL PRIMARY KEY,
  domain_id BIGINT NOT NULL REFERENCES domains(id),
  url TEXT NOT NULL,
  url_hash CHAR(40) NOT NULL,
  http_status INTEGER,
  last_http_status INTEGER,
  content_type TEXT,
  content_hash CHAR(64),
  title TEXT,
  depth INTEGER NOT NULL DEFAULT 0,
  discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_fetched_at TIMESTAMPTZ,
  last_indexed_at TIMESTAMPTZ,
  status TEXT NOT NULL,
  drop_reason TEXT,
  error_count INTEGER NOT NULL DEFAULT 0,
  storage_paths JSONB,
  UNIQUE (domain_id, url_hash)
);
CREATE INDEX idx_pages_status ON pages(status);
CREATE INDEX idx_pages_domain ON pages(domain_id);

-- 4) attachments
CREATE TABLE attachments (
  id BIGSERIAL PRIMARY KEY,
  page_id BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  domain_id BIGINT NOT NULL REFERENCES domains(id),
  source_url TEXT NOT NULL,
  file_name TEXT,
  mime_type TEXT,
  byte_size BIGINT,
  file_hash CHAR(64) NOT NULL,
  storage_path TEXT NOT NULL,
  text_path TEXT,
  extracted_text TEXT,
  extraction_status TEXT NOT NULL DEFAULT 'PENDING',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (domain_id, file_hash)
);
CREATE INDEX idx_attachments_page ON attachments(page_id);

-- 5) chunks
CREATE TABLE chunks (
  id BIGSERIAL PRIMARY KEY,
  chunk_id_sha1 CHAR(40) NOT NULL,
  qdrant_point_id UUID NOT NULL,
  page_id BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  attachment_id BIGINT REFERENCES attachments(id) ON DELETE CASCADE,
  is_attachment BOOLEAN NOT NULL DEFAULT FALSE,
  chunk_index INTEGER NOT NULL,
  token_len INTEGER NOT NULL,
  embedding_model TEXT NOT NULL,
  embedding_version INTEGER NOT NULL DEFAULT 1,
  embed_status TEXT NOT NULL DEFAULT 'PENDING',
  kb_status TEXT NOT NULL DEFAULT 'PENDING',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (page_id, embedding_version, chunk_index, is_attachment, attachment_id)
);
CREATE INDEX idx_chunks_page ON chunks(page_id);
CREATE INDEX idx_chunks_qdrant ON chunks(qdrant_point_id);
CREATE INDEX idx_chunks_kb_status ON chunks(kb_status);

-- 6) llm_usage
CREATE TABLE llm_usage (
  id BIGSERIAL PRIMARY KEY,
  page_id BIGINT REFERENCES pages(id),
  attachment_id BIGINT REFERENCES attachments(id),
  job_id BIGINT REFERENCES crawl_jobs(id),
  purpose TEXT NOT NULL,              -- refine | embedding
  model TEXT NOT NULL,
  prompt_tokens INTEGER NOT NULL,
  completion_tokens INTEGER NOT NULL,
  total_tokens INTEGER NOT NULL,
  cost_usd NUMERIC(12,6) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_llm_usage_job ON llm_usage(job_id);
```

> 외래키 순환 참조: `chunks.attachment_id`는 `attachments` 생성 후 추가. 마이그레이션에서 분리 단계로 작성 권장.

---

## B. 운영 런북 (3종)

### B.1 KB 차원 mismatch

**증상**: `/readyz`에서 `qdrant_dim != 3072`. ingestion 시 KSPO-KB-VALIDATION-DIM 에러.

**조치**:
1. `OPENAI_EMBED_MODEL` 환경변수 확인
2. Tiledesk가 사용하는 `index_name` 컬렉션 차원 확인 (Qdrant 콘솔)
3. 불일치 시:
   - 새 `index_name`(예: `tilellm_3l`) 컬렉션 생성
   - `.env`의 `QDRANT_INDEX_NAME` 변경 후 `docker compose restart api worker`
   - `full` Job 재시작 (도메인별)
   - 챗봇(Tiledesk) 측 engine 설정도 같이 변경 — 운영자에게 통지

### B.2 OpenAI 호출 실패 (인증 / 결제)

OpenAI API 호출이 일관 실패할 때 두 시나리오 중 하나. **HTTP status와 응답 본문 `error.type`** 으로 분기.

#### B.2.A 키 무효·만료 (HTTP 401 `invalid_api_key`)

**증상**: 모든 refine/embed가 401, 응답 본문 `error.type: invalid_api_key`.

**조치**:
1. OpenAI 대시보드에서 키 유효성 확인
2. 새 키 발급
3. `.env`의 `OPENAI_API_KEY` 갱신
4. `docker compose restart api worker`
5. 큐가 backoff 상태에서 자동 회복

#### B.2.B 카드 한도 소진·결제 실패 (HTTP 429 `insufficient_quota`)

**증상**:
- 모든 refine/embed가 429, 응답 본문 `error.type: insufficient_quota` 또는 `billing_not_active`
- `llm_usage` 월누계가 한도(150,000원) 근처
- 카드사 SMS·앱에 OpenAI 결제 실패 통보

**원인 검증**:
1. OpenAI 대시보드 → Billing → 카드 상태·잔액 확인
2. 카드사 앱 → 한도 소진 / 카드 정지 / 보안잠김 / 만료 확인
3. PG 누계 조회:
   ```sql
   SELECT date_trunc('month', created_at) AS month,
          SUM(cost_usd) AS cost_usd
     FROM llm_usage
   GROUP BY 1 ORDER BY 1 DESC LIMIT 3;
   ```

**조치 (원인별)**:
- **한도 소진**: 다음 결제일까지 대기 / 별도 카드 등록·교체 (KSPO 회계팀 협조)
- **카드 정지·보안잠김**: 카드사 고객센터 해제 후 ARQ `max_tries=5` 백오프로 자연 회복
- **카드 만료**: 새 카드를 OpenAI 대시보드에 등록 → Billing 탭 결제 재시도

**임시 조치** (시급한 적재 필요 시):
- OpenAI Pre-paid Credit 충전 (Billing → Credits) — 카드 결제 실패와 별개로 동작

**운영 정책**:
- 본 시스템은 자동 차단·자동 정지 **안 함** (round 1 §2.2 결정 — 알림만)
- ARQ는 `max_tries=5` + 지수 백오프 → 카드 복구 시 자동 재개
- 회복 후 `llm_usage` 비용 추세 확인 → 월 한도 재산정 검토

**예방**:
- KSPO 회계팀에 OpenAI 결제 실패 자동 통지 SOP
- 월 누계 80% 도달 시 사전 알림 — `05_devops_ops.md` §5.6 알림표 참조
- 백업 결제 수단(별도 카드) 사전 등록

### B.3 Tiledesk 다운

**증상**: `/api/qa` 검색이 안 되거나 5xx. 본 시스템은 Direct 모드라 적재 자체엔 영향 없음.

**조치**:
1. Tiledesk Compose의 `tilellm` 컨테이너 헬스 확인 (별도 Compose)
2. Tiledesk 측 운영자에게 통지
3. 본 시스템은 평소처럼 적재 지속 — 챗봇 검색만 일시 중단

> Job 폭주·비용 폭증·DLQ 같은 상세 런북은 v1.0 docs를 참고하거나 운영 중 필요해지면 추가.

---

## C. Tier 2/3 로드맵

Lite v2.0에서 빠진 기능. 운영 측정 결과에 따라 1~3개월 후 추가 검토.

| 항목 | Tier | 추가 시점 신호 |
|---|:---:|---|
| Crawl Rules (게시판 board/detail 셀렉터) | 2 | 게시판 본문 추출 품질 부족 측정 시 |
| 4단 적응형 청킹 + 헤더 3종 | 2 | 짧은 페이지 검색 매칭 약화 측정 시 |
| 카테고리 사전 + 승격 | 2 | 챗봇이 카테고리 필터링 요구 시 |
| Force Include / Drop 룰 (4 scope × 3 action) | 2 | LLM 의미 판별 오탐이 운영 거슬릴 때 |
| 보일러플레이트 자동 분석 (L3) | 2 | 셀렉터로 못 잡는 패턴 누적 시 |
| `board_refresh` Job | 2 | 주간 incremental로 신선도 부족 측정 시 |
| `since_refresh` Job (날짜 이후) | 2 | 특정 시점 이후 재크롤 필요 사례 발생 시 |
| Backfill Job 3종 (boilerplate/embedding/prompt) | 2 | 프롬프트·모델 변경 빈도 발생 시 |
| `cleanup_orphans` 정기 Job | 2 | PG↔Qdrant 차이 운영 거슬릴 때 |
| Hybrid 검색 활성화 | 2 | dense-only 정확도 부족 측정 시 |
| Stats 차트 대시보드 | 2 | 도메인 5개+ 비교 필요 시 |
| SSE 실시간 로그 | 2 | 5초 폴링 답답함 호소 시 |
| `worker-backfill` 별도 컨테이너 | 2 | 일반 incremental과 자원 경합 발생 시 |
| `scheduler` 별도 컨테이너 | 2 | 워커 재시작 시 cron 누락 발생 시 |
| LLM 출력 `categories`/`quality_score`/`drop_reason`/`language` | 2 | 챗봇·운영 측 요구 시 |
| Tags prefix 확장 (`c:`/`lang:`/`ru:` 등) | 2 | 카테고리/룰 도입 시 자연 추가 |
| SimHash dedup + `dup_group_id` | 3 | 페이지 간 근접 중복 다수 발견 시 |
| `audit_log` 테이블 | 3 | 다중 운영자 도입 시 |
| `page_history` 테이블 | 3 | 변경 이력 추적 필요 시 |
| `dead_jobs` UI | 3 | failed_jobs 수동 점검이 거슬릴 때 |
| `alerts` 테이블 + 8개 알림 룰 | 3 | 단순 이메일로 부족 시 |
| 다중 알림 채널 (웹훅/슬랙) | 3 | 이메일만 부족 시 |
| Prometheus exporter | 3 | 외부 대시보드 통합 필요 시 |
| 첨부 OCR (스캔 PDF) | 3 | OCR 필요 사례 누적 시 |
| `attachment_links` N:M 정규화 | 3 | 첨부 메타 row 폭증 시 |
| 다중 Admin · 권한 분리 | 3 | 운영자 늘어날 때 |
| JWT 인증 | 3 | API를 외부 서비스에 노출할 때 |

> 각 항목 추가는 **별도 마일스톤(M6+)** 으로 진행. 그때의 Task 지시서는 사람이 직접 작성하거나 본 설계서 v1.0을 참고.

---

## D. ARQ Task 카탈로그 (간소)

| Task | 큐 | 역할 |
|---|---|---|
| `enqueue_seeds` | default | Job 시드 URL을 frontier에 push |
| `fetch_page` | default | 단일 URL fetch + raw 적재 |
| `clean_page` | default | 본문 추출 + content_hash |
| `refine_page` | default | LLM 정제 + 의미 판별 |
| `chunk_and_embed` | default | 청킹 + 임베딩 + Qdrant Direct upsert |
| `download_attachment` | attach | 첨부 다운로드 + 텍스트 추출 |
| `run_incremental` | bg | 도메인 incremental 진입점 |
| `weekly_incremental_all` | bg | 모든 활성 도메인 주간 cron |
| `refresh_stats_views` | bg | PG 집계 뷰 갱신 (5분 주기) |

---

## E. PoC 체크리스트 — 4 항목 (간소)

| # | 항목 | 결정 시점 |
|---|---|---|
| P1 | Tiledesk 적재 후 Qdrant payload 키 컨벤션 캡처 (`page_content` vs `text`, `metadata` 중첩 여부) | 1일차 |
| P2 | 컬렉션 vector_size 자동 결정 vs 사전 생성 / `text-embedding-3-large` 호환성 | 1일차 |
| P3 | 같은 id 재적재 = upsert / 단건·필터 삭제 가능 여부 | 1일차 |
| P4 | `/api/qa`로 우리 데이터가 정상 검색되고 sources[].source가 우리 URL을 담는지 확인 | 2일차 |

> v1.0의 8 항목 중 다중 namespace / tags 매칭 모드 / tags 한도 / hybrid 품질은 Tier 2 시점에 검증.

`poc/` 디렉토리 구조:
```
poc/
├── checklist.md
├── curl/
│   ├── P1_capture.sh
│   ├── P2_dim.sh
│   ├── P3_upsert.sh
│   └── P4_search.sh
├── captures/
│   ├── P1_payload.json
│   └── ...
└── report.md
```

---

## F. 변경 이력

| 일자 | 버전 | 변경 |
|---|---|---|
| 2026-05-06 | v1.0 | 초판: Phase 0~10 통합 |
| 2026-05-07 | v2.0 (Lite) | 단순화: Phase 6, PG 6 테이블, API 14, UI 5페이지, 단일 worker, LLM 4필드, 청킹 2단. Tier 2/3 로드맵 명문화. |
| 2026-05-07 | v2.1 (본 시스템) | PRD round 1·2 결정 반영 — (1) Qdrant 듀얼 모드(개발/파일럿 자체 컨테이너 → 정식 운영 시 Tiledesk 외부 전환) (2) **Admin UI를 React + Tailwind + shadcn/ui SPA**로 변경, Jinja2/HTMX 제거 (3) **nginx 컨테이너 분리** — 정적자산·리버스 프록시·TLS 종료, host 80/443은 nginx만 노출 (4) 컨테이너 6개(개발/파일럿) → 5개(정식 운영). (5) 사내 프록시 경유 OpenAI 호출 (`HTTPS_PROXY`) (6) 월 비용 한도 150,000원, 월 누계 80% 사전 알림. (7) 런북 B.2를 키 무효 / 결제 실패로 분기. M0에 frontend bootstrap Task 추가 (총 20~25 Task). PRD [docs/prd/00_index.md](../prd/00_index.md) v1.4(7파일 분리)와 동기화. |
