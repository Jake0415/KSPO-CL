# 런북 C: Tiledesk 다운

> 출처: `docs/design/_appendix.md` §B.3 미러
> 분류: 외부 시스템 (본 시스템 적재엔 영향 없음)

## 증상

- Tiledesk 챗봇 위젯에서 검색이 안 되거나 5xx
- 사용자가 챗봇 응답을 받지 못한다는 보고
- Tiledesk-LLM `/api/qa` 엔드포인트가 응답 안 함

## 영향

- **본 시스템에는 영향 없음** — Direct 모드 적재라 Tiledesk-LLM `/api/ingestion`을 사용하지 않음
- 챗봇 검색만 일시 중단 (Qdrant 자체는 동작 가능)
- 본 시스템의 적재 파이프라인은 **평소처럼 지속**

## 진단 명령

```sh
# 1) Tiledesk Compose 상태 (별도 호스트/Compose)
ssh tiledesk-host 'docker compose ps'

# 2) Tiledesk-LLM 헬스
curl -fsS https://tiledesk.kspo.local/api/healthz || echo "tilellm DOWN"

# 3) Qdrant 자체는 살아있는지 (본 시스템 자체 컨테이너 또는 Tiledesk Qdrant)
curl -fsS $QDRANT_URL/collections | python -m json.tool

# 4) 본 시스템은 영향 없음 검증
curl -s http://localhost/readyz | python -m json.tool
docker compose logs --tail=20 worker | grep -E "indexed|kb_status"
```

## 조치 절차

1. Tiledesk Compose의 `tilellm` 컨테이너 헬스 확인 (별도 Compose)
2. Tiledesk 측 운영자에게 통지 (담당: KSPO IT — Tiledesk 운영 주체)
3. **본 시스템은 적재 지속** — 별도 조치 불필요
4. Tiledesk 복구 후 챗봇 검색이 새 데이터를 즉시 반영하는지 확인

## 확인

- Tiledesk-LLM `/api/healthz` → 200
- 챗봇 위젯에서 임의 질의 → 출처(URL) 포함 응답
- 본 시스템 `chunks.kb_status='OK'` 행은 평소처럼 증가 중

## 사후

- Tiledesk와 KSPO IT 측 운영 SLA 합의 (응답 시간, 복구 SLA)
- 본 시스템과 Tiledesk가 같은 호스트에 있는 경우 — 재시작 윈도우 동기화 (`docs/prd/05_nfr_infra.md` §5.1)

> Job 폭주·비용 폭증·DLQ 같은 상세 런북은 v1.0 docs를 참고하거나 운영 중 필요해지면 추가 (`docs/design/_appendix.md` §C — Tier 2/3 로드맵).
