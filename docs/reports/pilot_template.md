# KSPO 적재 시스템 — 파일럿 보고서 (템플릿)

> **작성**: <YYYY-MM-DD> / **작성자**: <이름> / **파일럿 기간**: <시작일> ~ <종료일>
> 본 템플릿을 복사해 `pilot_<YYYYMMDD>.md`로 저장 후 작성한다.

---

## 1. 요약 (Executive Summary)

- 파일럿 대상: KSPO 본사이트 (`www.kspo.or.kr`) 1 도메인
- 운영 기간: <N>주
- 결론: **정식 운영 진입 권장 / 보류 / 거절**
- 핵심 메시지(3줄):
  1. <예: 적재 커버리지 92% 달성, 목표 90% 초과>
  2. <예: 평균 신선도 4일, 목표 7일 이내>
  3. <예: 월 LLM 비용 87,000원, 한도 150,000원의 58%>

---

## 2. KPI 측정 결과

> 출처: `python scripts/kpi_measure.py --json` (전체 도메인 합산)
>     `GET /api/kpi/history?days=30` (일별 추이)

### 2.1 종합

| KPI | 권장 목표 | 측정값 | 달성 |
|---|---|---|---|
| 적재 커버리지 | ≥ 90% | <%> | ✓ / ✗ |
| 평균 신선도 | ≤ 7일 | <일> | ✓ / ✗ |
| Job 성공률 (최근 7일) | ≥ 95% | <%> | ✓ / ✗ |
| 월 LLM 비용 | ≤ 150,000원 | <원> | ✓ / ✗ |
| (참고) Tiledesk 챗봇 1차 해결률 | (운영 후 측정) | <%> | (Tiledesk 측 측정) |

### 2.2 도메인별 (현재는 1개)

| 도메인 | INDEXED | DROPPED | ERROR | 커버리지 |
|---|---|---|---|---|
| www.kspo.or.kr | <N> | <N> | <N> | <%> |

### 2.3 비용 분해

| 모델 | purpose | 누적 토큰 | 누적 비용(USD) | 누적 비용(KRW) |
|---|---|---|---|---|
| gpt-5.4-mini | refine | <N> | $<> | <원> |
| text-embedding-3-large | embedding | <N> | $<> | <원> |
| **합계** | | <N> | $<> | **<원>** |

> 환율: USD_TO_KRW_RATE=<R> (`.env` 기준 시점)

---

## 3. 발생 이슈

| 일자 | 분류 | 내용 | 조치 | 후속 |
|---|---|---|---|---|
| <YYYY-MM-DD> | 크롤·정제·임베딩·운영·기타 | <증상 + 영향> | <조치 + 결과> | 닫힘 / 추적 중 |

> 분류 가이드:
> - **크롤** = 사이트 fetch 실패, robots 충돌, 인코딩 등
> - **정제** = trafilatura 추출 부족, 한글 비율 부족 등
> - **임베딩** = OpenAI 401/429/timeout
> - **운영** = 컨테이너 재시작, 디스크, SMTP 등
> - **기타** = 그 외

---

## 4. KPI 권장 목표 합의 (PRD §9.3 #2)

운영 1개월 측정값 기반으로 KSPO ↔ 무한아이티 합의 후 본 시스템 `.env` 또는 운영 SOP에 반영.

| KPI | 잠정 목표(현재) | 합의 목표 | 사유 |
|---|---|---|---|
| 적재 커버리지 | 90% | <%> | <측정값 기반 + 여유율 X%> |
| 평균 신선도 | 7일 | <일> | <weekly cron 1주 + 운영 변동성> |
| Job 성공률 | 95% | <%> | <OpenAI 가용성 가정> |
| 월 LLM 비용 한도 | 150,000원 | <원> | <도메인 추가 계획 따라 조정> |

---

## 5. 정식 전환 권장 사항 (Tiledesk 외부 모드)

### 5.1 PoC 재검증 ([poc/checklist.md](../../poc/checklist.md) §P1~P4)

- [ ] **P1** Tiledesk Qdrant payload 키 캡처 → 본 시스템 `payload.py`와 일치
- [ ] **P2** 차원 호환성 (text-embedding-3-large 3072) 통과
- [ ] **P3** Upsert/Delete 동작 (Tiledesk wrapper or Direct filter)
- [ ] **P4** E2E 검색 (`/api/qa`로 우리 데이터 등장)

### 5.2 전환 절차 ([deploy.md §8](../runbook/deploy.md#8-qdrant-모드-전환-self_hosted--tiledesk-external))

- [ ] `.env` `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_INDEX_NAME`, `KB_BOOTSTRAP=external` 변경
- [ ] `docker compose up -d --force-recreate api worker`
- [ ] `/readyz` `qdrant_mode=external`, `qdrant_dim=3072` 확인
- [ ] 자체 `qdrant` 컨테이너·볼륨 삭제 → 6 services
- [ ] 모든 활성 도메인 `POST /api/jobs/full/{id}` 실행 → Tiledesk 컬렉션 적재 검증

---

## 6. 인계 산출물 확인 (PRD §8.3)

- [ ] 운영 매뉴얼 PDF (`dist/kspo-ingest_운영매뉴얼_v2.1.pdf`)
- [ ] 교육 슬라이드 PDF (`dist/training/kspo-ingest_교육슬라이드_v2.1.pdf`)
- [ ] Admin 1명에게 1회 교육 + 시연 완료
- [ ] [`docs/operations/04_handover_checklist.md`](../operations/04_handover_checklist.md) 모든 항목 통과
- [ ] 무한아이티 6개월 버그 지원 기간 시작일 합의 (서면)

---

## 7. KSPO 인수 결정

- [ ] **인수** / **보류** / **거절**
- 사유: <내용>
- 다음 단계:
  - 인수 시: Tiledesk 챗봇 공개 일정·홍보 계획
  - 보류 시: 미해결 항목·추가 검증 일정
  - 거절 시: 미해결 사항 명세 + 차후 재논의 시점

---

## 8. 부록

### 8.1 측정 명령

```bash
# KPI snapshot 1회 측정
python scripts/kpi_measure.py --json > pilot_kpi.json

# 30일 추이
curl -u admin:<pw> http://localhost/api/kpi/history?days=30 | jq . > pilot_kpi_history.json

# 도메인별 통계 뷰 직접 조회
docker compose exec postgres psql -U kspo -d kspo_ingest -c "SELECT * FROM v_stats_overview;"
```

### 8.2 운영 로그 발췌 (선택)

```
<event=fetch_ok ... >
<event=refine_ok ... >
<event=qdrant_upsert_ok ... >
```

### 8.3 서명

| 역할 | 이름 | 서명 | 일자 |
|---|---|---|---|
| 무한아이티 PM | | | |
| KSPO 사업관리 | | | |
| KSPO IT | | | |
| KSPO Admin | | | |
