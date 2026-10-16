---
marp: true
theme: default
paginate: true
header: "kspo-ingest 인계 교육 — Admin 일과"
---

# Admin 일과 시연

매일 5분 / 주 10분 / 이벤트 시 5~30분

---

## 매일 (5분)

1. `http://<운영>/login` 접속
2. 대시보드 `/` — 알림 배너·Job 현황 확인
3. `/jobs?status=FAILED` — 실패 Job 있으면 클릭
4. `error_message` 확인 → 런북 분기

**Tip**: 매일 오전 9시 첫 업무로 5분 루틴 권장

---

## 매주 일요일 03:00 KST 후 (10분)

자동 cron `weekly_incremental_all` 실행 → 활성 도메인 incremental Job

1. 일요일 오전 9시경 `/jobs?job_type=incremental` 검토
2. 도메인별 stats 요약:
   - `skipped` 많을수록 비용 절감 ✓
   - `errors` 또는 `removed` 급증 → 사이트 변경 신호 → 조사

---

## 도메인 추가

`/domains/new` →

| 필드 | 값 예시 |
|---|---|
| host | `www.kspo.or.kr` |
| scheme | `https` |
| max_pages | 5000 (작게 시작) |
| rate_limit_rps | 1.0 |
| respect_robots | true |

저장 → 자동 full Job → 1~3시간 후 INDEXED 확인

---

## 페이지 강제 재크롤

긴급 컨텐츠 수정 후 챗봇 답변 동기화:

```bash
POST /api/jobs/refresh-url
{ "url": "https://www.kspo.or.kr/path", "force": true }
```

또는 UI `/pages/{id}` → "강제 재크롤"

**rate limit**: 분당 60회 (그 이상은 429)

---

## PII 노출 발견 시

1. `/domains/{id}` → `deny_patterns`에 정규식 추가
2. 즉시 삭제: `DELETE /api/domains/{id}` 후 재등록 (단기 무거움)
3. KSPO IT 통보 — 챗봇 답변 캐시도 검토

---

## 자주 보는 화면

| URL | 용도 |
|---|---|
| `/` | KPI 대시보드 |
| `/domains` | 도메인 목록·생성·편집 |
| `/jobs` | 실행 이력 |
| `/pages` | 페이지 검색·상세 |
| `/settings` | 비밀번호·환경변수 미러 |

---

## 실습 1 (10분)

1. 데모 도메인 1개 등록
2. full Job 트리거
3. SUCCESS 도달 확인
4. 페이지 1개에 force refresh
5. 도메인 비활성화 → 재활성화

---

## 다음

`02_runbook_walkthrough.md` — 사고 시 행동 시연
