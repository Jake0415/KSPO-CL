# Operator Acceptance Test (OAT) Runbook

> **Version:** 1.0
> **Date:** 2026-07-05
> **Role:** QA Manager + Operations Engineer
> **Duration:** 약 4시간 (첫 실행 기준)
> **Prerequisites:** Docker Desktop 설치, 터미널 접근, .env 파일 준비

---

## Pre-Flight Checklist

| # | 항목 | 확인 |
|---|------|------|
| 1 | Docker Desktop 실행 중 | `docker info` 정상 |
| 2 | `.env` 파일 준비 (`.env.example` 복사 후 실제 키 입력) | `OPENAI_API_KEY` 설정됨 |
| 3 | 포트 충돌 없음 (80, 8080, 5432, 6379, 6333) | `lsof -i :80` 비어있음 |
| 4 | 소스 코드 최신 (main branch) | `git status` clean |

---

## OAT-01: Docker Compose 기동

**목적:** 전체 스택(7 컨테이너)이 정상 기동되는지 확인

**실행:**
```bash
cd docker
cp ../.env.example .env
# .env 편집: OPENAI_API_KEY, ADMIN_PASSWORD_BCRYPT, SESSION_SECRET 입력
docker compose up -d
docker compose ps
```

**확인 위치:** 터미널 출력

**기대 결과:**
```
NAME            STATUS          PORTS
nginx           Up (healthy)    0.0.0.0:80->80/tcp
web             Up              3000/tcp
api             Up (healthy)    8080/tcp
worker          Up              -
postgres        Up (healthy)    5432/tcp
redis           Up (healthy)    6379/tcp
qdrant          Up (healthy)    6333/tcp
```
- 모든 서비스 `Up` 상태
- postgres, redis, api는 `(healthy)` 표시

**실패 사례:**
| 증상 | 원인 | 조치 |
|------|------|------|
| api `Exit 1` | .env 누락 또는 PG 연결 실패 | `docker compose logs api` 확인, .env 검증 |
| postgres `restarting` | 데이터 볼륨 권한 | `docker volume rm kspo-ingest_pgdata` 후 재시작 |
| qdrant `Exit` | 메모리 부족 | Docker Desktop RAM 4GB+ 확보 |

**PASS 기준:** 7개 서비스 모두 `Up` 상태, 60초 이내 안정화

---

## OAT-02: Health Check & Swagger

**목적:** API가 정상 응답하고 문서가 접근 가능한지 확인

**실행:**
```bash
# Health check
curl -s http://localhost/api/healthz | jq .

# Readiness (PG + Qdrant + Cost 확인)
curl -s http://localhost/api/readyz | jq .

# Swagger UI
open http://localhost/api/docs
```

**기대 결과:**
- `/healthz`: `{"status": "ok"}`
- `/readyz`: `qdrant_dim: 3072`, `pg: true`, `monthly_cost_krw: 0`
- Swagger: 23개 endpoint 목록 표시

**PASS 기준:** healthz 200, readyz에 qdrant_dim=3072 표시

---

## OAT-03: Web UI 접근

**목적:** Admin 대시보드가 정상 로드되는지 확인

**실행:**
```
브라우저: http://localhost
```

**기대 결과:**
- 로그인 페이지 표시
- 관리자 로그인 성공 (admin / 설정한 비밀번호)
- 대시보드: KPI 4개 카드 표시 (초기값 0)

**PASS 기준:** 로그인 성공 + 대시보드 렌더링

---

## OAT-04: Domain 생성

**목적:** 크롤링 대상 도메인을 등록할 수 있는지 확인

**실행 (UI):**
1. 좌측 메뉴 > Domains > Add Domain
2. 입력:
   - Host: `www.kspo.or.kr`
   - Scheme: `https`
   - Display Name: `KSPO 본사이트`
   - Max Pages: `50` (테스트용 소규모)
   - Max Depth: `3`
   - Rate Limit RPS: `1.0`

**실행 (API 대안):**
```bash
curl -X POST http://localhost/api/domains \
  -H "Content-Type: application/json" \
  -b "session=<쿠키값>" \
  -d '{
    "host": "www.kspo.or.kr",
    "scheme": "https",
    "display_name": "KSPO 본사이트",
    "max_pages": 50,
    "max_depth": 3,
    "rate_limit_rps": 1.0
  }' | jq .
```

**기대 결과:**
- 201 Created
- Response에 `id`, `host`, `is_active: true`

**PASS 기준:** Domain ID 반환, UI 목록에 표시

---

## OAT-05: Full Crawl 실행

**목적:** 전체 파이프라인(fetch->clean->refine->chunk->embed->upsert)이 동작하는지 확인

**실행:**
```bash
# Full crawl job 생성
curl -X POST "http://localhost/api/jobs/full/1" \
  -b "session=<쿠키값>" | jq .
```

**확인 위치:**
- UI > Jobs 페이지 (5초 자동 갱신)
- Worker 로그: `docker compose logs -f worker`

**기대 결과:**
- Job status 변화: `PENDING` → `RUNNING` → `SUCCESS`
- Stats에 `fetched`, `indexed` 값 > 0
- Worker 로그에 `chunk_index_ok` 이벤트 출력
- 소요 시간: 50페이지 × ~5초/페이지 = 약 4-5분

**실패 사례:**
| 증상 | 원인 | 조치 |
|------|------|------|
| Job `FAILED` + `openai_error` | API Key 무효 | .env의 OPENAI_API_KEY 확인 |
| Job `FAILED` + `qdrant_unreachable` | Qdrant 미기동 | `docker compose restart qdrant` |
| 매우 느림 (>15분) | Rate limit 또는 네트워크 | RPS 확인, 프록시 설정 확인 |

**PASS 기준:** Job SUCCESS + indexed > 0

---

## OAT-06: DB 적재 확인

**목적:** PostgreSQL에 페이지/청크/비용 데이터가 정상 적재되었는지 확인

**실행:**
```bash
docker compose exec postgres psql -U kspo -d kspo_ingest -c "
  SELECT status, count(*) FROM pages GROUP BY status;
  SELECT count(*) as total_chunks FROM chunks WHERE kb_status='OK';
  SELECT purpose, sum(cost_usd) as total_cost FROM llm_usage GROUP BY purpose;
  SELECT quadrant, count(*) FROM doc_quality GROUP BY quadrant;
"
```

**기대 결과:**
```
 status  | count
---------+------
 INDEXED | 30+
 DROPPED | 0~5

 total_chunks
--------------
 50+

 purpose   | total_cost
-----------+-----------
 refine    | 0.01~0.10
 embedding | 0.01~0.05

 quadrant | count
----------+------
 Q1       | 20+
 Q2       | 5+
```

**PASS 기준:** INDEXED 페이지 존재 + chunks KB_STATUS='OK' > 0 + Q1 문서 존재

---

## OAT-07: Qdrant Collection 확인

**목적:** 3개 컬렉션이 생성되고 벡터가 적재되었는지 확인

**실행:**
```bash
# 컬렉션 목록
curl -s http://localhost:6333/collections | jq '.result.collections[].name'

# tilellm 컬렉션 상태
curl -s http://localhost:6333/collections/tilellm | jq '{
  points_count: .result.points_count,
  vectors_count: .result.vectors_count,
  dimension: .result.config.params.vectors.size
}'

# kspo_knowledge 컬렉션
curl -s http://localhost:6333/collections/kspo_knowledge | jq '.result.points_count'

# kspo_archive 컬렉션
curl -s http://localhost:6333/collections/kspo_archive | jq '.result.points_count'
```

**기대 결과:**
- 3개 컬렉션 존재: `tilellm`, `kspo_knowledge`, `kspo_archive`
- tilellm: dimension=3072, points_count > 0
- kspo_knowledge: points_count >= tilellm (Q1+Q2+Q3 모두 포함)
- kspo_archive: points_count = 0 (초기)

**PASS 기준:** tilellm에 벡터 존재 + dimension=3072

---

## OAT-08: Payload 구조 확인

**목적:** Qdrant payload가 Tiledesk 호환 스키마인지 확인

**실행:**
```bash
# 첫 번째 포인트의 payload 확인
curl -s http://localhost:6333/collections/tilellm/points/scroll \
  -H "Content-Type: application/json" \
  -d '{"limit": 1, "with_payload": true}' | jq '.result.points[0].payload'
```

**기대 결과:**
```json
{
  "page_content": "...(텍스트)...",
  "metadata": {
    "id": "sha1-hash",
    "source": "https://www.kspo.or.kr/...",
    "namespace": "kspo",
    "type": "text",
    "domain_host": "www.kspo.or.kr",
    "title": "...",
    "summary": "...",
    "keywords": ["...", "..."],
    "posted_at": "2026-...",
    "is_attachment": false,
    "embedding_version": 1,
    "quality_score": 0.7~1.0,
    "quadrant": "Q1",
    "freshness_score": 0.5~1.0,
    "trust_score": 1.0,
    "tags": ["d:www.kspo.or.kr", "v:1"]
  }
}
```

**PASS 기준:** `page_content` + `metadata.source` + `metadata.quality_score` > 0 존재

---

## OAT-09: Collection Routing 확인

**목적:** Q1 문서는 tilellm+knowledge 양쪽에, Q2/Q3는 knowledge에만 존재하는지 확인

**실행:**
```bash
# Q1 문서의 point_id 하나 선택 (DB에서)
docker compose exec postgres psql -U kspo -d kspo_ingest -c "
  SELECT c.qdrant_point_id, dq.quadrant
  FROM chunks c
  JOIN doc_quality dq ON c.page_id = dq.page_id
  WHERE dq.quadrant = 'Q1' AND c.kb_status = 'OK'
  LIMIT 1;
"

# 해당 point가 tilellm에 존재하는지
curl -s "http://localhost:6333/collections/tilellm/points/<point_id>"

# 해당 point가 kspo_knowledge에도 존재하는지
curl -s "http://localhost:6333/collections/kspo_knowledge/points/<point_id>"
```

**기대 결과:**
- Q1 point: tilellm ✅ + kspo_knowledge ✅
- Q2/Q3 point: tilellm ❌ + kspo_knowledge ✅

**PASS 기준:** Q1 문서가 양쪽 컬렉션에 존재

---

## OAT-10: Incremental Crawl 확인

**목적:** 이미 크롤된 페이지를 다시 크롤할 때 content_hash가 동일하면 skip하는지 확인

**실행:**
```bash
# Incremental job
curl -X POST "http://localhost/api/jobs/incremental/1" \
  -b "session=<쿠키값>" | jq .
```

**확인:**
```bash
# Worker 로그에서 "clean_hash_unchanged" 또는 "skipped" 확인
docker compose logs worker | grep -c "skipped\|hash_unchanged"
```

**기대 결과:**
- Job SUCCESS
- 대부분의 페이지가 `skipped` (content 미변경)
- LLM 비용 = 0 또는 매우 적음 (변경된 페이지만 refine)
- 소요 시간: Full 대비 80%+ 감소

**PASS 기준:** skipped 페이지 > 0 + LLM 비용 Full 대비 현저히 감소

---

## OAT-11: Duplicate Detection 확인

**목적:** 동일/유사 콘텐츠가 중복 인덱싱되지 않는지 확인

**실행:**
```bash
docker compose exec postgres psql -U kspo -d kspo_ingest -c "
  SELECT page_id, duplicate_score, quadrant
  FROM doc_quality
  WHERE duplicate_score < 1.0
  ORDER BY duplicate_score ASC
  LIMIT 10;
"
```

**기대 결과:**
- `duplicate_score = 1.0`: 고유 문서
- `duplicate_score = 0.0`: 중복 감지됨 (Q4 또는 embedding skip)
- 대부분 1.0 (정상 — 고유 문서가 대다수)

**PASS 기준:** duplicate_score 컬럼에 0.0~1.0 범위의 실제 값이 기록됨

---

## OAT-12: QA API 호출

**목적:** 챗봇 QA 엔드포인트가 정상 작동하는지 확인

**실행:**
```bash
curl -X POST http://localhost/api/qa \
  -H "Content-Type: application/json" \
  -d '{"question": "국민체육진흥공단은 무엇을 하는 기관인가요?"}' | jq .
```

**기대 결과:**
```json
{
  "answer": "국민체육진흥공단은 ... [1] ...",
  "sources": [
    {"source": "https://www.kspo.or.kr/...", "title": "...", "score": 0.8+}
  ],
  "citations": [
    {"index": 1, "source_url": "https://...", "title": "..."}
  ],
  "log_id": 1,
  "latency_ms": 2000~5000
}
```

**실패 사례:**
| 증상 | 원인 | 조치 |
|------|------|------|
| `"answer": null` | Qdrant 검색 결과 0건 | tilellm 컬렉션 확인 |
| 500 Error | OpenAI API 문제 | API Key 확인, rate limit 확인 |
| Hallucination | Context 미매칭 | 벡터 quality 확인 |

**PASS 기준:** answer 텍스트 + sources 1개 이상 + citation 존재

---

## OAT-13: Graceful Shutdown

**목적:** Worker가 진행 중 작업을 완료한 후 종료하는지 확인

**실행:**
```bash
# Job 실행 중 Worker 중지
curl -X POST "http://localhost/api/jobs/full/1" -b "session=<쿠키값>"
sleep 5
docker compose stop worker
docker compose logs worker | tail -20
```

**기대 결과:**
- 로그에 `worker_stopped` 이벤트 출력
- 진행 중이던 페이지는 FETCHED/CLEANED 등 중간 상태
- Qdrant/PG 데이터 손상 없음

**PASS 기준:** `worker_stopped` 로그 출력 + 데이터 무결성

---

## OAT-14: Worker Restart & Recovery

**목적:** Worker 재시작 후 시스템이 정상 복구되는지 확인

**실행:**
```bash
docker compose start worker
sleep 10
# 새 Job이 정상 실행되는지 확인
curl -X POST "http://localhost/api/jobs/incremental/1" \
  -b "session=<쿠키값>" | jq .
```

**기대 결과:**
- Worker 재시작 후 정상 동작
- 새 Job이 PENDING → RUNNING → SUCCESS

**PASS 기준:** 재시작 후 Job 정상 완료

---

## OAT-15: Budget Guard 확인

**목적:** 월 예산 초과 시 LLM 호출이 자동 차단되는지 확인

**실행:**
```bash
# 현재 비용 확인
curl -s http://localhost/api/readyz | jq '.monthly_cost_krw'

# Budget을 현재 비용보다 낮게 설정하여 테스트
# .env에서 OPENAI_MONTHLY_BUDGET_KRW=1 (1원)으로 변경 후 api 재시작
docker compose restart api worker
sleep 5

# Incremental 실행 → refine skip 로그 확인
curl -X POST "http://localhost/api/jobs/incremental/1" -b "session=<쿠키값>"
docker compose logs worker | grep "budget_exceeded_skip"
```

**기대 결과:**
- Worker 로그에 `budget_exceeded_skip` 출력
- LLM 비용 추가 없음

**주의:** 테스트 후 OPENAI_MONTHLY_BUDGET_KRW를 원래 값(150000)으로 복원

**PASS 기준:** budget_exceeded_skip 로그 출력됨

---

## OAT-16: Monitoring & Metrics

**목적:** 운영 모니터링 데이터가 수집되고 있는지 확인

**실행:**
```bash
# Prometheus metrics
curl -s http://localhost/api/metrics | head -20

# KPI
curl -s http://localhost/api/kpi/latest -b "session=<쿠키값>" | jq .

# 로그 구조 확인
docker compose logs api | tail -5 | jq .
```

**기대 결과:**
- `/metrics`: Prometheus 형식 텍스트 (pages_fetched_total, llm_requests_total 등)
- KPI: coverage_pct, avg_freshness_days, job_success_rate_pct, monthly_cost_krw
- 로그: JSON 1줄/이벤트, `ts`, `level`, `event` 필드 포함

**PASS 기준:** metrics 응답 + KPI 데이터 존재 + JSON 로그 정상

---

## OAT-17: Archive 동작 확인

**목적:** freshness 만료 문서가 Q4로 전환되고 Qdrant에서 삭제되는지 확인

**실행:**
```bash
# 테스트용: 특정 문서의 freshness_score를 0.1로 수동 변경
docker compose exec postgres psql -U kspo -d kspo_ingest -c "
  UPDATE doc_quality SET freshness_score = 0.1
  WHERE page_id = (SELECT page_id FROM doc_quality WHERE quadrant = 'Q1' LIMIT 1);
"

# Archive cron 수동 trigger (worker에서 실행)
docker compose exec worker python -c "
import asyncio
from kspo_ingest.tasks.cron import archive_expired_documents
ctx = {}  # 실제 worker context 필요
# 또는 다음 05:00 KST cron 대기
"
```

**대안:** 다음 날 05:00 KST cron 실행 후 확인:
```bash
docker compose exec postgres psql -U kspo -d kspo_ingest -c "
  SELECT page_id, quadrant, archived_at
  FROM doc_quality
  WHERE archived_at IS NOT NULL;
"
```

**PASS 기준:** archived_at NOT NULL 레코드 존재 (cron 실행 후)

---

## OAT-18: Cleanup & Teardown

**실행:**
```bash
docker compose down -v  # 볼륨 포함 삭제
```

---
