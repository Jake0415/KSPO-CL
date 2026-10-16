# Release Validation Checklist

> **Version:** 1.0
> **Purpose:** 운영 배포 전 최종 검증. 각 항목 PASS 후 Sign-off.

## Infrastructure

| # | 항�� | 기대 | 실제 | PASS |
|---|------|------|------|------|
| 1 | Docker Compose 7 서비스 기동 | 모두 Up (healthy) | | □ |
| 2 | /healthz 응답 | `{"status":"ok"}` | | □ |
| 3 | /readyz 응답 | qdrant_dim=3072, pg=true | | □ |
| 4 | Qdrant 3 컬렉션 존재 | tilellm, kspo_knowledge, kspo_archive | | □ |
| 5 | PG 마이그레이션 완료 | 6개 revision 적용 | | □ |
| 6 | Redis 연결 | ARQ queue 접근 가능 | | □ |
| 7 | nginx 80 응답 | Web UI 정상 로드 | | □ |

## Authentication

| # | 항목 | 기대 | 실제 | PASS |
|---|------|------|------|------|
| 8 | Admin 로그인 | 200 + session cookie | | □ |
| 9 | 잘못된 비밀번호 5회 | 429 + 잠금 메시지 | | □ |
| 10 | 5분 후 잠금 해제 | 로그인 성공 | | □ |
| 11 | 비밀번호 변경 | 새 비밀번호로 재로그인 | | □ |

## Data Pipeline

| # | 항목 | 기대 | 실제 | PASS |
|---|------|------|------|------|
| 12 | Domain 생성 (API) | 201 + id 반환 | | □ |
| 13 | Full Crawl Job 생성 | PENDING 상태 | | □ |
| 14 | Job RUNNING 전환 | Worker 로그 확인 | | □ |
| 15 | Job SUCCESS 완료 | stats.indexed > 0 | | □ |
| 16 | Pages INDEXED 상태 | SELECT count > 0 | | □ |
| 17 | Chunks kb_status=OK | SELECT count > 0 | | □ |
| 18 | LlmUsage 기록 | refine + embedding 행 존재 | | □ |
| 19 | DocQuality Q1 존재 | quadrant='Q1' count > 0 | | □ |

## Vector DB

| # | 항목 | 기대 | 실제 | PASS |
|---|------|------|------|------|
| 20 | tilellm points > 0 | Q1 문서 벡터 존재 | | □ |
| 21 | kspo_knowledge points >= tilellm | Q1+Q2+Q3 포함 | | □ |
| 22 | Payload schema 정합 | page_content + metadata 구조 | | □ |
| 23 | quality_score > 0 in payload | 실제 점수 기록 | | □ |
| 24 | Collection routing 정확 | Q1=양쪽, Q2/Q3=knowledge만 | | □ |

## Incremental & Dedup

| # | 항목 | 기대 | 실제 | PASS |
|---|------|------|------|------|
| 25 | Incremental Job 실행 | SUCCESS | | □ |
| 26 | content_hash 미변경 skip | skipped 로그 존재 | | □ |
| 27 | LLM 비용 감소 | Full 대비 80%+ 절감 | | □ |
| 28 | duplicate_score 기록 | 0.0~1.0 실제 값 | | □ |

## QA & RAG

| # | 항목 | 기대 | 실제 | PASS |
|---|------|------|------|------|
| 29 | /api/qa 응답 | answer + sources + citations | | □ |
| 30 | Citation 정확성 | [1] source_url이 실제 KSPO URL | | □ |
| 31 | Hallucination 없음 | 답변이 source 내용에 근거 | | □ |
| 32 | 관련 없는 질문 | "답변할 수 없습니다" 류 응답 | | □ |
| 33 | QaLog 기록 | DB에 question/answer/latency 존재 | | □ |

## Operational

| # | 항목 | 기대 | 실제 | PASS |
|---|------|------|------|------|
| 34 | /metrics 응답 | Prometheus 형식 | | □ |
| 35 | JSON 로그 출력 | ts/level/event 구조 | | □ |
| 36 | Worker graceful stop | worker_stopped 로그 | | □ |
| 37 | Worker restart recovery | 재시작 후 Job 정상 | | □ |
| 38 | Budget 80% 알림 | cost_monitor 로그 확인 | | □ |
| 39 | Budget 100% hard stop | budget_exceeded_skip ���그 | | □ |
| 40 | Cron 등록 (6개) | ARQ cron 목록 확인 | | □ |

## Sign-off

| 역할 | 이름 | 날짜 | 판정 |
|------|------|------|------|
| QA Manager | | | □ GO / □ NO-GO |
| Product Owner | | | □ GO / □ NO-GO |
| Tech Lead | | | □ GO / □ NO-GO |
| Ops Engineer | | | □ GO / □ NO-GO |

**판정 기준:**
- 40개 항목 중 38개 이상 PASS → **GO**
- FAIL 항목이 #12~#24 (Pipeline/Vector) 중 하나라도 → **NO-GO**
- FAIL 항목이 #29~#33 (QA/RAG) 중 2개 이상 → **NO-GO**
