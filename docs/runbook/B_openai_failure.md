# 런북 B: OpenAI 호출 실패 (인증·결제)

> 출처: `docs/design/_appendix.md` §B.2 미러
> 분류: 시스템 레벨 (refine·embed 차단)

## 증상

- 모든 refine/embed 호출이 실패. **HTTP status와 응답 본문 `error.type`** 으로 분기.

## 영향

- refine·embed 정지 → M2~M3 파이프라인 중단
- 자체 Qdrant 적재만 멈춤 (Tiledesk 검색은 기존 데이터로 계속 동작)
- crawl_jobs `RUNNING` Job은 ARQ `max_tries=5` + 지수 백오프로 재시도 → 카드 복구 시 자연 재개

## 진단 명령

```sh
# 1) 최근 OpenAI 호출 로그 (마지막 200줄)
docker compose logs --tail=200 api worker | grep -E "openai|401|429|insufficient_quota|invalid_api_key"

# 2) 이번 달 LLM 누계 비용 (KRW 환산은 USD_TO_KRW_RATE 적용)
docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c \
  "SELECT date_trunc('month', created_at) AS m, SUM(cost_usd) AS cost_usd, COUNT(*) AS calls
   FROM llm_usage GROUP BY 1 ORDER BY 1 DESC LIMIT 3;"

# 3) /readyz의 monthly_cost_krw / budget_used_pct 필드 (M5.T5.1 머지 후 활성)
curl -s http://localhost/readyz | python -m json.tool
```

## 분기 결정

- `error.type == invalid_api_key` (HTTP 401) → **B.2.A**
- `error.type == insufficient_quota | billing_not_active` (HTTP 429) → **B.2.B**

---

## B.2.A — 키 무효·만료

### 증상
- 모든 refine/embed가 401, 응답 본문 `error.type: invalid_api_key`

### 조치 절차
1. OpenAI 대시보드(https://platform.openai.com/api-keys)에서 키 유효성 확인
2. 새 키 발급
3. `.env`의 `OPENAI_API_KEY` 갱신
4. `docker compose restart api worker`
5. 큐가 backoff 상태에서 자동 회복

### 확인
- `docker compose logs api | grep -i openai_ok` 발생
- 진행 중 `crawl_jobs.status='RUNNING'` Job이 다시 진전 (stats.refined 또는 stats.indexed 증가)

### 사후
- 키 교체 주기 캘린더 등록 (90일 권장)
- `OPENAI_API_KEY`를 시크릿 매니저로 도입 검토 (Tier 2)

---

## B.2.B — 카드 한도 소진·결제 실패

### 증상
- 모든 refine/embed가 429, 응답 본문 `error.type: insufficient_quota` 또는 `billing_not_active`
- `llm_usage` 월누계가 한도(`OPENAI_MONTHLY_BUDGET_KRW`, default 150,000원) 근처
- 카드사 SMS·앱에 OpenAI 결제 실패 통보

### 원인 검증
1. OpenAI 대시보드 → Billing → 카드 상태·잔액 확인
2. 카드사 앱 → 한도 소진 / 카드 정지 / 보안잠김 / 만료 확인
3. PG 누계 조회 (위 진단 명령 #2)

### 조치 (원인별)
- **한도 소진**: 다음 결제일까지 대기 / 별도 카드 등록·교체 (KSPO 회계팀 협조)
- **카드 정지·보안잠김**: 카드사 고객센터 해제 후 ARQ `max_tries=5` 백오프로 자연 회복
- **카드 만료**: 새 카드를 OpenAI 대시보드 등록 → Billing 탭 결제 재시도

### 임시 조치 (시급한 적재 필요 시)
- OpenAI Pre-paid Credit 충전 (Billing → Credits) — 카드 결제 실패와 별개로 동작

### 운영 정책
- 본 시스템은 자동 차단·자동 정지 **안 함** (PRD round 1 §2.2 결정 — 알림만)
- ARQ `max_tries=5` + 지수 백오프 → 카드 복구 시 자동 재개
- 회복 후 `llm_usage` 비용 추세 → 월 한도 재산정 검토

### 확인
- `docker compose logs api | grep -i openai_ok` 발생
- 신규 `llm_usage` 행 생성 (`SELECT MAX(created_at) FROM llm_usage`)

### 사후
- KSPO 회계팀에 OpenAI 결제 실패 자동 통지 SOP
- 월 누계 80% 도달 시 사전 알림 동작 확인 (M5.T5.1 산출물)
- 백업 결제 수단(별도 카드) 사전 등록
