# KSPO IT 운영 작업

> 대상: KSPO IT(인프라·보안 담당). 분기·월·이벤트 단위.

## 분기 1회 (1시간)

| 항목 | 동작 |
|---|---|
| OpenAI API 키 갱신 | 회사 보안 정책상 분기 회전. `.env` `OPENAI_API_KEY` 교체 → `docker compose up -d --force-recreate api worker` |
| 사내 프록시 설정 | KSPO 망 변경 시 `.env` `HTTPS_PROXY` / `NO_PROXY` 갱신 |
| 디스크 사용량 | `du -sh storage/ pgdata_volume/ qdrant_data/` — 70% 도달 시 [§디스크](03_troubleshooting.md#q5-디스크-사용량-급증) 참조 |
| 의존성 보안 점검 | `uv pip list --outdated` 또는 GitHub Dependabot 알림 검토 |

## 월 1회 (30분)

```bash
python scripts/kpi_measure.py --json > kpi_$(date +%Y%m).json
```

위 출력으로 사업관리에 보고. 추가로:

- 월 LLM 비용 한도(`OPENAI_MONTHLY_BUDGET_KRW`, 기본 150,000원) 초과 여부
- 80% 알림 메일 수신 이력 검토 — `SMTP_TO_RECIPIENTS` 메일함
- `v_cost_daily` 뷰 직접 조회: `SELECT day, model, purpose, cost_usd FROM v_cost_daily LIMIT 30;`

## 정기 재시작 윈도우 (매월 둘째 일요일 02:00 KST)

> ⚠ weekly cron이 03:00 KST 실행 — **02:30 이전 종료 권장** (30분 buffer).

```bash
cd /opt/kspo-ingest      # 운영 호스트 경로 (예시)
git pull --ff-only       # 새 릴리스 있을 시
docker compose -f docker/docker-compose.yml down
# 보안 패치 / OS 업데이트 진행
docker compose -f docker/docker-compose.yml up -d
sleep 10
curl -fsS http://localhost/readyz | jq .
```

`readyz` 검증 항목 (모두 정상이어야):

| 키 | 정상 값 |
|---|---|
| `db` | `"ok"` |
| `redis` | `"stub"` 또는 `"ok"` |
| `qdrant_dim` | `3072` |
| `qdrant_mode` | `"self_hosted"` 또는 `"external"` |
| `proxy_configured` | `true` (사내망 시) |
| `monthly_cost_krw` | 숫자 (정상 응답) |

## TLS 인증서 갱신 (사내 정책 주기)

```bash
# 기존 백업
mv docker/nginx/certs/{server.crt,server.crt.bak}
mv docker/nginx/certs/{server.key,server.key.bak}
# 신규 인증서 배치
cp /path/to/new.crt docker/nginx/certs/server.crt
cp /path/to/new.key docker/nginx/certs/server.key
docker compose restart nginx
curl -k https://localhost/healthz   # TLS 검증
```

## 사고 대응 — 카드 한도 소진 ([런북 B.2.B](../runbook/B_openai_failure.md))

OpenAI 결제 실패로 모든 LLM 호출이 401/429:

1. 즉시 회계팀에 결제 보고
2. 임시 조치: `OPENAI_MONTHLY_BUDGET_KRW`를 0으로 설정하면 새 Job이 인큐되지 않도록 차단 (Tier 2)
3. 결제 재개 후 `OPENAI_API_KEY` 재발급 → `.env` 교체 → `docker compose up -d --force-recreate api worker`
4. ERROR 상태 Job들에 대해 `POST /api/jobs/incremental/{domain_id}` 트리거 → 재시도

## Tiledesk 측 정식 운영 전환 (파일럿 종료 시)

[배포 런북 §8](../runbook/deploy.md#8-qdrant-모드-전환-self_hosted--tiledesk-external) 참조.

**필수 사전조건**: PoC P1~P4 재검증 완료 (`poc/checklist.md`).

## 인프라 변경 SOP

- 컨테이너 추가/제거 → docker-compose.yml 변경 → PR 리뷰 필요
- 데이터베이스 스키마 변경 → Alembic revision → migrations 컨테이너로 적용
- 환경변수 추가 → `.env.example` 갱신 + `.env` 운영본 패치 (재시작 필요)
