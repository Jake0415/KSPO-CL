# 운영 개요 — KSPO 적재 시스템 v2.1

## 시스템 구성

| 컴포넌트 | 역할 | 컨테이너 |
|---|---|---|
| nginx | 80 포트 진입점, web/api로 reverse proxy | `nginx:1.27-alpine` |
| web | Next.js 16 Admin UI(:3300, standalone) | 빌드 이미지 |
| api | FastAPI(:8080) — 도메인·Job·페이지·헬스·알림 API | 빌드 이미지 |
| worker | ARQ — 크롤·정제·청킹·임베딩·Qdrant 적재 + cron 3종 | 빌드 이미지 |
| postgres | PG 16 — 6 테이블 + 통계 뷰 2종 | `postgres:16-alpine` |
| redis | ARQ broker + rate limit + 알림 dedup | `redis:7-alpine` |
| qdrant | (개발/파일럿) 벡터 DB. 정식 운영 시 Tiledesk 외부 인스턴스로 전환 | `qdrant/qdrant:latest` |

**총 7개 컨테이너** (개발/파일럿). 정식 전환 시 qdrant 제거 → 6개.

## 데이터 흐름 (한 페이지 기준)

```
URL  ──▶ fetch_page  ──▶ raw HTML 저장(storage/raw/)
                  │
                  ▼
          clean_page (Trafilatura + 셀렉터 블랙리스트)
                  │
        content_hash 변경?
        ├── Yes ─▶ refine_page (gpt-5.4-mini, 정제+요약+키워드)
        │              │
        │              ▼
        │       chunk_and_index
        │       (chunk → embed → Qdrant upsert → INDEXED)
        │
        └── No  ─▶ skipped (LLM 비용 0)
```

## 주요 일정

| 주기 | 동작 |
|---|---|
| 매 분 | `check_budget_alerts` cron — 월 누계 80% 도달 시 SMTP 1회 알림 |
| 5분 | `refresh_stats_views` — `v_stats_overview` 갱신 (대시보드 KPI 노출용) |
| 매주 일요일 03:00 KST | `weekly_incremental_all` — 활성 도메인 전체 incremental Job |
| 매월 둘째 일요일 02:00 KST | KSPO IT 정기 재시작 윈도우 (보안 패치) |

## 데이터 보관 정책

- **storage/raw/** — 원본 HTML, 영구 보관(재정제용)
- **PG `pages.content_hash`** — 변경 감지 키. raw 변경 없으면 LLM 호출 차단
- **Qdrant 청크** — 도메인 비활성화/삭제 시 cascade 정리
- **백업 미운영** — 손실 시 재크롤·재정제·재임베딩으로 복원 (CLAUDE.md 결정)

## 핵심 KPI 4종

| KPI | 정의 | 목표 |
|---|---|---|
| 적재 커버리지 | INDEXED / (INDEXED + DROPPED + ERROR) | ≥ 90% |
| 적재 신선도 | last_indexed_at - discovered_at 평균 | ≤ 7일 |
| Job 성공률 | 최근 7일 SUCCESS / 총 Job | ≥ 95% |
| 월 LLM 비용 | 이번 달 누계 KRW (gpt-5.4-mini + text-embedding-3-large) | ≤ 150,000원 |

측정: `python scripts/kpi_measure.py --json` 또는 Admin UI 대시보드.

## 다음

- [01_admin_workflow.md](01_admin_workflow.md) — Admin이 매일·매주 하는 일
- [02_kspo_it_workflow.md](02_kspo_it_workflow.md) — KSPO IT 분기·월·이벤트 작업
- [../runbook/A_kb_dim_mismatch.md](../runbook/A_kb_dim_mismatch.md) — 사고 대응 런북 A
