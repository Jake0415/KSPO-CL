# 02. 파이프라인 — Crawl + Clean + Refine

## 2.1 책임 범위

Admin이 등록한 도메인의 시드 URL부터 BFS 크롤링 → 본문 추출 → LLM 정제 → 의미 판별까지. 청킹·임베딩·적재는 다음 Phase(03).

## 2.2 도메인 등록 옵션 (`domains` 테이블, 단순화)

```sql
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
```

v1.0 대비 빠진 컬럼: `scope_mode`/`path_prefix`/`include_subdomains`/`attachment_policy`/`tiledesk_namespace`.
범위는 항상 호스트 정확 일치(서브도메인은 Admin이 별도 등록), 첨부는 항상 다운로드.

## 2.3 URL 정규화

1. scheme/host 소문자, 기본 포트(80/443) 제거, fragment 제거
2. 경로 비면 `/` 추가, 외엔 trailing slash 보존
3. 쿼리 파라미터 알파벳 정렬 + 트래킹(utm_*/fbclid/gclid) 제거
4. KSPO 게시판 식별 파라미터(`bbsId`,`nttId`)는 보존
5. `url_hash = sha1(정규화된 URL)` — 중복 검사 키

## 2.4 Frontier (Redis)

| 키 | 자료구조 | 용도 |
|---|---|---|
| `frontier:{job_id}` | List | 방문 대기 |
| `seen:{job_id}` | Set | 등록된 url_hash |
| `inflight:{job_id}` | Set | 처리 중 |
| `host_bucket:{host}` | ZSET | rate limit 토큰 |

## 2.5 Fetch 정책

- 정적: `httpx.AsyncClient` (HTTP/2)
- 동적: Playwright (`use_playwright=true`인 도메인만)
- 타임아웃: connect 10s / read 30s
- 응답 크기 상한 10MB
- 재시도: tenacity, 5xx/네트워크 5회 지수 백오프, Retry-After 존중
- robots.txt: 기본 준수, `respect_robots=false`로 운영 시 로그 경고

## 2.6 첨부파일 처리 (`attachments`)

```sql
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
```

> v1.0의 `attachment_links`(N:M) 테이블 제거. 같은 첨부가 여러 페이지에 인용되면 중복 row 허용(파일은 file_hash로 dedup, 메타만 N개).

추출 도구: pypdf / python-docx / openpyxl / python-pptx. **OCR 미포함** (Tier 2). 100MB 상한.

## 2.7 페이지 레코드 (`pages`)

```sql
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
```

## 2.8 본문 추출 (Cleaner)

우선순위:
1. `<main>`/`<article>`/`role=main`
2. Trafilatura
3. Readability-lxml
4. 휴리스틱(텍스트 밀도)

> v1.0의 `crawl_rules`(게시판 detail_selectors) 제거. Trafilatura가 게시판 본문을 70~80% 잡는다는 가정. 부족한 사이트는 Tier 2에서 추가.

추출 후 후처리: 공백 압축(단락 경계 보존), 비가시 문자 제거, 표→파이프 텍스트.

## 2.9 인코딩 탐지

1. HTTP Content-Type charset
2. `<meta charset>`
3. BOM
4. chardet 추정
5. '?' 비율 임계 초과 시 EUC-KR/CP949 재시도

## 2.10 Selector Blacklist (L2)

기본값(전역, `configs/selectors.yaml`):

```yaml
- header
- nav
- footer
- aside
- .skip
- .gnb
- .lnb
- .snb
- .breadcrumb
- .location
- .share
- .sns
- .print
- .related
- .popular
- .copyright
- .copy
- .policy
- .sitemap
- .bbs-search
- .bbs-paging
- .paging
- '#hd'
- '#ft'
- '#header'
- '#footer'
- script
- style
- noscript
```

도메인별 추가는 `domains.selector_blacklist`로 누적. UI 미제공(Tier 2) — 필요 시 SQL UPDATE 또는 `configs`로 관리.

## 2.11 Content Hash 정규화

```python
def normalize_for_hash(text: str) -> str:
    s = re.sub(r'\s+', ' ', text).strip()
    s = re.sub(r'조회수\s*[:：]?\s*\d[,\d]*', '', s)
    s = re.sub(r'오늘\s*날짜\s*[:：]?.*?(?=\s|$)', '', s)
    return hashlib.sha256(s.encode('utf-8')).hexdigest()
```

`pages.content_hash` 미변경 시 LLM·임베딩 단계 skip(비용 0).

## 2.12 LLM 정제 (Refiner)

### 사전 룰

| 조건 | 조치 |
|---|---|
| `len(body_text) < 100` | DROPPED('too_short'), LLM 호출 생략 |
| 제목이 '로그인/오류/404' 정확 일치 | DROPPED('error_page') |
| `korean_ratio < 0.30` | DROPPED('non_korean') |

`korean_ratio = 한글 음절 수 / 모든 letter 수`. 임계는 환경변수.

### Structured Output (4 필드)

```json
{
  "name": "RefinerOutput",
  "schema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["refined_text","is_meaningful","summary","keywords"],
    "properties": {
      "refined_text":  { "type": "string" },
      "is_meaningful": { "type": "boolean" },
      "summary":       { "type": "string" },
      "keywords":      { "type": "array", "items": {"type":"string"}, "maxItems": 15 }
    }
  },
  "strict": true
}
```

> v1.0 대비 빠진 필드: `drop_reason`(사후 룰로 결정), `categories`(Tier 2), `language`(사전 필터), `quality_score`(Tier 2), `notes`.

### 시스템 프롬프트 (요약)

```
한국어 콘텐츠 정제 전문가.

(1) 정제: 머리글/꼬리글/광고/내비 잔여 노이즈 제거. 표·리스트는 자연어로.
    원문에 없는 정보 추가 금지(환각 방지).

(2) 의미 판별: 검색·답변에 인용될 정보가 충분한지 판단.
    의미 없음: 빈/로그인/에러/메뉴/사이트맵, 본문 < 100자.

(3) 요약: 2~4문장.

(4) 키워드: 5~15개. 고유명사·기관명·법령명·날짜 우선.

응답은 지정된 JSON Schema로만.
```

### 비용 추적

```sql
CREATE TABLE llm_usage (
  id BIGSERIAL PRIMARY KEY,
  page_id BIGINT REFERENCES pages(id),
  attachment_id BIGINT REFERENCES attachments(id),
  job_id BIGINT REFERENCES crawl_jobs(id),
  purpose TEXT NOT NULL,       -- refine | embedding
  model TEXT NOT NULL,
  prompt_tokens INTEGER NOT NULL,
  completion_tokens INTEGER NOT NULL,
  total_tokens INTEGER NOT NULL,
  cost_usd NUMERIC(12,6) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_llm_usage_job ON llm_usage(job_id);
```

## 2.13 처리 큐 (단일 체인)

```
fetch_page  → pages.status=FETCHED  → enqueue clean_page
clean_page  → no_change면 종료 / change면 enqueue refine_page
refine_page → DROPPED 또는 enqueue chunk_and_embed (다음 Phase)
extract_links → frontier (BFS depth+1)
download_attachment → 첨부 텍스트 추출 → enqueue chunk_and_embed (첨부 청크)
```

모두 `queue:default` (첨부 다운로드만 `queue:attach`).
