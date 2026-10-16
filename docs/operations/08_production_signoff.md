# Production Sign-off Checklist

> **Purpose:** 최종 운영 배포 승인 문서. 모든 항목 충족 시 Go Live.

---

## 승인 조건

### 필수 (ALL MUST PASS)

| # | Category | Condition | Evidence Required | Status |
|---|----------|-----------|-------------------|--------|
| 1 | **Code** | Full Test Suite 0 failures | pytest 출력 캡처 | □ |
| 2 | **Code** | Ruff 0 violations | ruff 출력 캡처 | □ |
| 3 | **Infra** | Docker 7서비스 healthy | `docker compose ps` 캡처 | □ |
| 4 | **Infra** | /readyz qdrant_dim=3072 | curl 응답 캡처 | □ |
| 5 | **Pipeline** | Full Crawl Job SUCCESS (50+ pages) | Job detail 캡처 | □ |
| 6 | **Pipeline** | Incremental Job skipped pages > 0 | Worker 로그 캡처 | □ |
| 7 | **Vector** | tilellm points > 0 | Qdrant API 응답 | □ |
| 8 | **Vector** | Collection routing 정확 | Q1 양쪽 존재 확인 | □ |
| 9 | **QA** | /api/qa 응답 + citation | 응답 JSON 캡처 | □ |
| 10 | **RAG** | 50개 질문 Hallucination <= 10% | 평가 결과 문서 | □ |
| 11 | **Security** | Admin 로그인 + lockout 동작 | 스크린샷 | □ |
| 12 | **Ops** | Budget guard 동작 | budget_exceeded_skip 로그 | □ |
| 13 | **Ops** | Worker graceful shutdown | worker_stopped 로그 | □ |
| 14 | **Ops** | Worker restart recovery | 재시작 후 Job 성공 | □ |

### 권고 (SHOULD PASS)

| # | Category | Condition | Status |
|---|----------|-----------|--------|
| 15 | Security | Non-root container | □ |
| 16 | Ops | Prometheus metrics 수집 | □ |
| 17 | Ops | Cron 6개 등록 확인 | □ |
| 18 | Docs | Runbook 최신화 | □ |
| 19 | Perf | 50 pages < 10분 완료 | □ |
| 20 | Perf | QA latency < 5초 | □ |

---

## 승인 판정 기준

| 결과 | 조건 |
|------|------|
| **GO** | 필수 14개 모두 PASS + 권고 4개 이상 PASS |
| **CONDITIONAL GO** | 필수 12개 이상 PASS + 실패 항목이 #15~#20 내 |
| **NO-GO** | 필수 항목 중 #5~#9 (Pipeline/Vector/QA) 하나라도 FAIL |

---

## 배포 후 확인 (Post-Deployment Verification)

배포 완료 후 30분 이내 확인:

| # | 항목 | 명령 |
|---|------|------|
| 1 | /healthz 응답 | `curl https://production-url/api/healthz` |
| 2 | /readyz 응답 | `curl https://production-url/api/readyz` |
| 3 | Web UI 로그인 | 브라우저 접속 |
| 4 | QA API 테스트 | `curl -X POST https://production-url/api/qa -d ...` |
| 5 | Worker 로그 정상 | `docker compose logs worker --since 5m` |

---

## Rollback 절차

배포 후 문제 발생 시:

```bash
# 1. 즉시 이전 버전으로 롤백
docker compose down
git checkout <이전_태그>
docker compose up -d

# 2. DB 마이그레이션 호환 확인
# (forward-only migration이므로 DB rollback은 하지 않음)
# Qdrant 데이터는 유지됨 (벡터는 재크롤로 복원 가능)

# 3. 상태 확인
curl http://localhost/api/healthz
curl http://localhost/api/readyz
```

---

## 서명

| 역할 | 이름 | 서명 | 날짜 |
|------|------|------|------|
| Product Owner | | | |
| QA Manager | | | |
| Tech Lead | | | |
| Security Officer | | | |
| Ops Lead | | | |

**최종 판정:** □ GO / □ CONDITIONAL GO / □ NO-GO

**사유:**

_______________________________________________
