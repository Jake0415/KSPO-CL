# 05. DevOps · 운영

## 5.1 Docker Compose (6 서비스 — 개발/파일럿 / 정식 운영 시 5개)

```yaml
name: kspo-ingest
services:
  nginx:
    build: { context: .., dockerfile: docker/Dockerfile.web }
    depends_on:
      api: { condition: service_started }
    ports: ["80:80", "443:443"]
    volumes: [../docker/nginx/certs:/etc/nginx/certs:ro]
    environment:
      - TZ=Asia/Seoul
    restart: unless-stopped

  api:
    build: { context: .., dockerfile: docker/Dockerfile.api }
    env_file: [../.env]
    depends_on:
      postgres: { condition: service_healthy }
      redis:    { condition: service_healthy }
    expose: ["8080"]   # host에 노출 안 함 (nginx 경유)
    volumes: [storage:/data, ../configs:/app/configs:ro]
    environment:
      - TZ=Asia/Seoul
    restart: unless-stopped

  worker:
    build: { context: .., dockerfile: docker/Dockerfile.worker }
    env_file: [../.env]
    environment:
      - WORKER_QUEUES=default,attach,bg
      - WORKER_CONCURRENCY=4
      - TZ=Asia/Seoul
    depends_on:
      postgres: { condition: service_healthy }
      redis:    { condition: service_healthy }
    volumes: [storage:/data, ../configs:/app/configs:ro]
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    env_file: [../.env]
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      TZ: Asia/Seoul
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL","pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 10s
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: ["redis-server","--save","''","--appendonly","no"]
    volumes: [redisdata:/data]
    healthcheck: { test: ["CMD","redis-cli","ping"], interval: 10s }
    environment: { TZ: Asia/Seoul }
    restart: unless-stopped

  qdrant:                    # 개발/파일럿 전용. 정식 운영 시 서비스·볼륨 제거
    image: qdrant/qdrant:latest
    volumes: [qdrant_data:/qdrant/storage]
    expose: ["6333"]         # host에 노출 안 함 (사내망 only)
    environment: { TZ: Asia/Seoul }
    restart: unless-stopped

  migrations:
    build: { context: .., dockerfile: docker/Dockerfile.migrations }
    env_file: [../.env]
    depends_on: { postgres: { condition: service_healthy } }
    profiles: ["migrations"]
    command: ["alembic","upgrade","head"]

volumes: { pgdata: {}, redisdata: {}, qdrant_data: {}, storage: {} }
networks:
  default:
    name: kspo-ingest-net
```

> v1.0의 `worker-pipeline x 2` / `worker-backfill` / `scheduler` / `playwright` / `tilellm` 모두 미포함.
> v2.1 (본 시스템) 추가: `nginx` (정적자산 + 리버스 프록시 + TLS 종료), `qdrant` (개발/파일럿 전용).
> **정식 운영 전환 시**: `qdrant` 서비스·볼륨 삭제, `QDRANT_URL`을 Tiledesk 외부 인스턴스로 변경 → 5 services. PoC P1~P4 재검증 의무 (PRD §4.2).

## 5.2 Qdrant 운용 모드 (듀얼)

| 단계 | Qdrant 위치 | `QDRANT_URL` |
|---|---|---|
| 개발 / 테스트 / PoC / 파일럿 | 본 Compose의 `qdrant` 컨테이너 | `http://qdrant:6333` |
| 정식 운영 | **Tiledesk 외부 인스턴스** | KSPO·Tiledesk 측 제공값 |

**전환 절차** (PRD §4.2 — 파일럿 종료 후):
1. Tiledesk 측 `index_name`·차원·payload 키 컨벤션 확보
2. 본 시스템 `.env` `QDRANT_URL` 변경
3. PoC P1~P4 재검증 (페이로드 키·차원 호환성·upsert·e2e 검색)
4. 검증 통과 시 `qdrant` 서비스 종료 + 볼륨 삭제 (`docker compose down qdrant && docker volume rm kspo-ingest_qdrant_data`)
5. `full` Job 재실행으로 Tiledesk 컬렉션 채우기

**Tiledesk Compose 접근 방법** (정식 운영 시 — 둘 중 하나):
- Tiledesk Compose 네트워크에 `external: true`로 합류
- Tiledesk가 Qdrant 포트(6333)를 호스트로 노출 → `host.docker.internal:6333` (또는 사내 IP)

## 5.3 Dockerfile (3종 + nginx 1종)

### Dockerfile.api / Dockerfile.worker / Dockerfile.migrations
```dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libxml2 libxslt1.1 curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml /app/
RUN pip install -U pip && pip install -e .[api]
COPY src /app/src
COPY migrations /app/migrations
EXPOSE 8080
CMD ["uvicorn","kspo_ingest.api.main:app","--host","0.0.0.0","--port","8080"]
```

`Dockerfile.worker`, `Dockerfile.migrations`는 같은 베이스에서 CMD만 다름.

### Dockerfile.web (multi-stage: Node 빌드 + nginx serve)
```dockerfile
# 1) build SPA
FROM node:20-alpine AS build
WORKDIR /app
COPY web/package.json web/package-lock.json /app/
RUN npm ci
COPY web/ /app/
RUN npm run build  # → /app/dist

# 2) nginx serve + reverse proxy
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY docker/nginx/nginx.conf /etc/nginx/nginx.conf
COPY docker/nginx/certs /etc/nginx/certs:ro
EXPOSE 80 443
```

> `web/` 폴더는 frontend 코드 (M0.T0.4 frontend bootstrap에서 스캐폴딩). nginx config는 SPA fallback + `/api` `/files` reverse proxy + gzip + immutable Cache-Control.

## 5.4 환경변수

`.env.example` 기준. v1.0 대비 빠진 변수: `INTERNAL_TOKEN`, `SEARCH_API_TOKEN`, `OPENAI_RPM/TPM`(필요 시 추가), `KB_HYBRID`, `EMBED_INCLUDE_HEADER`(고정 활성), `RAW_RETENTION_DAYS`(영구 고정), `CHUNK_VERY_SHORT_THRESHOLD_TOKENS`.

**v2.1 추가 변수**:
- `HTTPS_PROXY` / `HTTP_PROXY` — 사내 프록시 경유 OpenAI 호출 (`api`, `worker` 컨테이너만 적용)
- `NO_PROXY` — `localhost,127.0.0.1,postgres,redis,qdrant,host.docker.internal` + Admin 등록 KSPO 도메인
- `OPENAI_MONTHLY_BUDGET_KRW` — 월 비용 한도(default 150000). 80% 도달 시 알림 (§5.7)
- `TZ=Asia/Seoul` — 모든 컨테이너 일괄 적용

## 5.5 로깅

Loguru JSON 1줄/이벤트, stderr.

의무 필드: `ts, level, service, logger, request_id, job_id?, page_id?, event, latency_ms?`

원본 본문 텍스트는 로그 출력 금지(길이/해시만). API 키/세션 토큰 마스킹.

## 5.6 메트릭 (PG 집계 뷰만)

> v1.0의 Prometheus exporter 제거. PG 집계 뷰로 충분.

```sql
CREATE MATERIALIZED VIEW v_stats_overview AS
SELECT d.id AS domain_id, d.host,
       COUNT(p.*) FILTER (WHERE p.status='INDEXED')        AS indexed,
       COUNT(p.*) FILTER (WHERE p.status='DROPPED')        AS dropped,
       COUNT(p.*) FILTER (WHERE p.status='ERROR')          AS errors,
       SUM(c.token_len)                                    AS total_tokens
FROM domains d
LEFT JOIN pages p  ON p.domain_id=d.id
LEFT JOIN chunks c ON c.page_id=p.id
GROUP BY d.id, d.host;

CREATE VIEW v_cost_daily AS
  SELECT date_trunc('day', created_at) AS day,
         model, purpose, SUM(cost_usd) AS cost
    FROM llm_usage GROUP BY 1,2,3;
```

`REFRESH MATERIALIZED VIEW`는 5분 주기 ARQ cron.

## 5.7 알림 (간소화)

| 이벤트 | 임계 | 채널 |
|---|---|---|
| KB 차원 mismatch | 즉시 | 이메일 + UI 배너 |
| OpenAI 인증 실패 (HTTP 401) | 즉시 | 이메일 + UI 배너 |
| OpenAI 결제 실패 (HTTP 429 `insufficient_quota`) | 즉시 | 이메일 + UI 배너 (런북 B.2.B 참조) |
| **월 LLM 누계 80% 도달** | 매 ARQ tick (분 단위) | 이메일 + UI 배너 |
| Job 실패 | 즉시 | UI 배너 |

> v1.0의 8개 룰 + 웹훅 + alerts 테이블 모두 제거. 이메일 1개 + UI 배너만. 5개 임계 외엔 운영자가 수동 모니터링.
> 일일 비용 임계는 운영하지 않는다(round 1 §2.2 결정 — 월누계만 관리). 월 누계 임계는 `OPENAI_MONTHLY_BUDGET_KRW × 0.8` 또는 `OPENAI_MONTHLY_BUDGET_USD × 0.8` 중 환경변수로 결정.

## 5.8 에러·재시도

- ARQ task `max_tries=5`, 지수 백오프(상한 5분), Retry-After 존중
- 5회 실패 후에는 ARQ의 `failed_jobs` Redis 키에 남음 (별도 PG 테이블 미운영)
- Admin은 `redis-cli LRANGE failed_jobs 0 -1`로 확인, 또는 SQL: `SELECT * FROM crawl_jobs WHERE status='FAILED'`
- 시스템 레벨 실패(KB 차원 mismatch, OpenAI 401)는 fail-fast — Job FAILED 처리

## 5.9 데이터 보존 (백업 미운영)

source of truth는 원천 사이트. 손실 시 재크롤·재정제·재임베딩으로 복원.

| 자산 | 보존 |
|---|---|
| storage/raw | 영구 |
| storage/refined | 영구 |
| storage/attachments | 영구 |
| PG 메타 | 운영 중에만 |
| Qdrant | 운영 중에만 |

> **Fallback SOP** — KSPO IT 정책상 백업 운영을 요구하는 경우 PRD §5.4 표 참조 (storage/* 일일 rsync to KSPO NAS).

## 5.10 테스트

| 계층 | 도구 | 범위 |
|---|---|---|
| 단위 | pytest, pytest-asyncio, respx, freezegun | URL 정규화·hash·청킹·사전 룰 |
| 통합 | docker-compose.test.yml + qdrant stub | DB ↔ 모듈, ARQ 흐름 |
| E2E | 로컬 미러 + 실제 OpenAI(저비용) + 실제 Tiledesk·Qdrant | 도메인 1곳 종단, 검색 회귀 |

## 5.11 마일스톤

| M | 내용 | Task 수 |
|---|---|---|
| M0 | 부트스트랩 (Docker, Alembic, /healthz·/readyz, CI, **frontend bootstrap**) | 4~5 |
| M1 | 데이터 모델(6 테이블) + Admin 골격 + 도메인 CRUD | 4~5 |
| M2 | Crawl + Clean + Refine 파이프라인 | 4 |
| M3 | Chunk + Embed + Qdrant Direct + 첨부 다운로드/추출 | 3~4 |
| M4 | Incremental + Manual Refresh + 주간 cron | 2~3 |
| M5 | 운영 (로깅·테스트·문서·런북) | 3~4 |

총 20~25 Task (v2.1 — frontend bootstrap 추가로 lite 원안 +2~3). v1.0의 ~50 Task 대비 절반.

## 5.12 Claude Code 작업 지시 템플릿

```markdown
# M{n}.T{n.m} — <제목>

## Goal
<무엇을 만드는지, 본 설계서의 어느 절을 구현하는지>

## Files
- src/kspo_ingest/.../*.py
- tests/.../test_*.py (단위 테스트 N+ cases)

## Spec
<핵심 룰>

## Acceptance
- 동작 기준
- pytest -k <key> all green
- ruff check 0 issues

## 참고
- docs/design/0X.md §X.Y
```

## 5.13 PR 분할

- 1 PR ≈ 1 Task, 3~10 파일, 200~600 추가 라인
- 단위 테스트 + 1줄 changelog 필수
- 마이그레이션 추가 시 revision id 명시

## 5.14 운영 런북 (3종 — 부록 §B 참조)

- A. KB 차원 mismatch
- B. OpenAI 인증 실패
- C. Tiledesk 다운

> v1.0의 Job 폭주·비용 폭증 런북은 단순화 정책상 부록에서 짧게 언급만.
