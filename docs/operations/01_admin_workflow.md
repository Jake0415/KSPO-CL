# Admin 일과

> 대상: KSPO 운영 담당자(단일 Admin 계정).
> 시간: 매일 ~5분 / 매주 ~10분 / 이벤트 시 5~30분.

## 매일 (5분)

1. **Admin UI 접속** — `http://<운영호스트>/login` (자격은 KSPO IT 발급)
2. **대시보드 `/`** 확인:
   - KPI 카드 — 적재 커버리지·Job 성공률·월 비용 (M5.T5.4 결선)
   - 알림 배너 — 한도 80% 도달 또는 ERROR 페이지 급증 시 표시
3. **실행 이력 `/jobs`** — `status=FAILED` 항목 있으면 클릭하여 `error_message` 확인
4. ERROR Job이 있으면 [런북 B](../runbook/B_openai_failure.md) 또는 [run book C](../runbook/C_tiledesk_down.md)로 분기

## 매주 일요일 03:00 KST 이후 (10분)

`weekly_incremental_all` cron이 활성 도메인 전체에 incremental Job을 enqueue.

1. `/jobs?job_type=incremental` 필터 — 일요일 새벽 Job 결과 검토
2. 도메인별 stats 요약:
   - `skipped` 비율이 높을수록 비용 절감 (변경 없는 페이지)
   - `refined` 증가 = LLM 비용 발생 — 비용 카드 동기 확인
   - `errors` 또는 `removed` 급증 시 [§자주 발생하는 문제](03_troubleshooting.md) 참조
3. 새로 ERROR 상태가 된 페이지 스팟 체크 — `/pages?status=ERROR`

## 도메인 추가 (이벤트)

1. `/domains/new`
   - **호스트** (필수) — 예: `www.kspo.or.kr`
   - **스키마** — http/https
   - **최대 깊이/페이지** — 사이트 규모에 맞춰 조정 (작게 시작 권장)
   - **rate_limit_rps** — 1.0~1.5 권장 (사이트 부하 고려)
   - **respect_robots** — 일반적으로 true. 예외 시 KSPO IT 협의 후 false
2. 저장 후 자동 `POST /api/jobs/full/{id}` 트리거됨
3. 1~3시간 후 (사이트 규모에 따라 다름) `/jobs/{id}` 상세에서 `status=SUCCESS` + INDEXED 페이지 수 확인
4. 부족 시 `/domains/{id}` 편집 → max_pages 증가 → 다시 full Job

## 페이지 강제 재크롤 (이벤트)

특정 페이지를 즉시 재처리해야 할 때 (예: 컨텐츠 긴급 수정 후 챗봇 답변 동기화):

```
POST /api/jobs/refresh-url
{
  "url": "https://www.kspo.or.kr/path/to/page",
  "force": true
}
```

또는 Admin UI `/pages/{id}` 상세 → "강제 재크롤" 버튼 (M5.T5.4 결선).

> 분당 60회 rate limit — 폭주 시 429 응답.

## PII / 민감정보 노출 발견 시

1. `/domains/{id}` → **deny_patterns** 입력란에 정규식/glob 패턴 추가
   - 예: `^/private/.*` (해당 패턴은 다음 incremental 시 미수집)
2. 이미 적재된 페이지 즉시 삭제:
   - 단기: `DELETE /api/domains/{id}` 후 재등록 (전체 재크롤) — 무거움
   - 단건: `pages/{id}` → "도메인에서 제외" (Tier 2)
3. 노출이 챗봇 답변에 이미 사용 중이면 KSPO IT에 즉시 보고 (런북 별도)

## 비밀번호 변경

`/settings` → 비밀번호 변경 (M5.T5.2 결선). 분기 1회 권장.

## 로그아웃

`AppShell` 좌하단 LogOut 아이콘 — 세션 쿠키 삭제, `/login` 리다이렉트.
