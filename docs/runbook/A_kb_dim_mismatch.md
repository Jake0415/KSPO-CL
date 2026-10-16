# 런북 A: KB 차원 mismatch

> 출처: `docs/design/_appendix.md` §B.1 미러
> 분류: 시스템 레벨 (적재 차단)

## 증상

- `/readyz` 응답에 `qdrant_dim != 3072` 또는 `qdrant_dim == 0`
- `/readyz` HTTP 503
- ingestion 시 `KSPO-KB-VALIDATION-DIM` 에러 로그
- worker 로그: `event=qdrant_upsert_fail reason=dim_mismatch`

## 영향

- 임베딩 → Qdrant upsert 단계가 전부 실패
- 페이지가 INDEXED 상태에 도달하지 못함 (`chunks.kb_status='ERROR'`)
- 본 시스템 외 영향 없음 (챗봇 검색은 기존 데이터로 계속 동작)

## 진단 명령

```sh
# 1) 본 시스템이 사용하는 임베딩 모델 확인
docker compose exec api env | grep OPENAI_EMBED_MODEL

# 2) Qdrant 컬렉션 차원 확인
curl -s http://qdrant:6333/collections/$QDRANT_INDEX_NAME | python -m json.tool

# 3) /readyz 종합 응답
curl -s http://localhost/readyz | python -m json.tool
```

## 조치 절차

1. `OPENAI_EMBED_MODEL` 환경변수 확인 — 기본값 `text-embedding-3-large` (3072 dim)
2. Tiledesk가 사용하는 `index_name` 컬렉션 차원 확인 (Qdrant 콘솔 또는 위 진단 명령 #2)
3. 불일치 시:
   - 새 `index_name` 컬렉션 생성 (예: `tilellm_3l`)
   - `.env`의 `QDRANT_INDEX_NAME` 변경
   - `docker compose restart api worker`
   - 영향받는 도메인의 `full` Job 재시작
   - 챗봇(Tiledesk) 측 `engine.index_name` 설정도 같이 변경 — 운영자에게 통지

## 확인

- `/readyz` → `qdrant_dim == 3072` + 200
- 임의 도메인의 `full` Job 1회 → `chunks.kb_status='OK'` 행 생성 + Qdrant 포인트 적재
- 챗봇 측 검색이 새 컬렉션에서 정상 응답

## 사후

- `OPENAI_EMBED_MODEL` 변경 시 본 사고 재발 가능 — 모델 변경은 PR + Tiledesk 운영자 사전 통지를 강제하는 SOP 작성
- Tiledesk 정식 운영 전환 직전 PoC P2(차원 호환성) 재검증 의무 (PRD §4.2)
