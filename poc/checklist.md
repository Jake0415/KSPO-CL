# PoC 체크리스트 (Lite — 4 항목)

본 시스템은 Tiledesk가 운영하는 Qdrant에 **Direct 모드로 적재**하고, 챗봇 검색은 Tiledesk-LLM `/api/qa`가 같은 Qdrant를 읽는 구조다. 따라서 다음 4개 항목을 본격 코딩 전 1~2일에 검증한다.

> 본 Lite 버전은 v1.0의 8 항목 중 핵심 4개만 다룬다. 나머지(다중 namespace, tags 매칭 모드, tags 한도, hybrid 품질)는 Tier 2 도입 시점에 측정.

---

## 환경 준비 (반나절)

```bash
# 1) Tiledesk 별도 Compose 가동
git clone https://github.com/Tiledesk/tiledesk-llm
cd tiledesk-llm/docker
cp .env.example .env
# OPENAI_API_KEY, JWT_SECRET_KEY, REDIS_URL 채움
docker compose --profile qdrant --profile app-base up --build

# 2) PoC 작업 폴더
mkdir -p poc/curl poc/captures
```

---

## P1. Tiledesk 적재 후 Qdrant payload 키 캡처 ⭐

Tiledesk-LLM `/api/ingestion`으로 1건 적재 후 Qdrant 콘솔에서 만들어진 포인트의 정확한 payload 키 컨벤션을 캡처.

```bash
# JWT 토큰
TOKEN=$(python -c "import jwt; print(jwt.encode({'sub':'poc'}, 'YOUR_JWT_SECRET'))")

# 1건 적재
curl -X POST http://localhost:8000/api/ingestion \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "poc-payload-1",
    "type": "text",
    "content": "이것은 PoC 테스트입니다.",
    "source": "https://example.com/poc",
    "namespace": "poc_payload",
    "embedding": "text-embedding-ada-002",
    "engine": {"name":"qdrant","url":"http://qdrant:6333","index_name":"tilellm"}
  }'

# Qdrant 콘솔(http://localhost:6333/dashboard) → tilellm 컬렉션 → 포인트 1건 조회
# payload JSON 전체를 poc/captures/P1_payload.json 저장
```

**확인할 것**
- 본문 텍스트가 들어가는 키: `page_content`인가 `text`인가
- 메타 위치: `metadata` 중첩인가 평면(flat)인가
- `source`/`namespace`/`id`/`type`/`tags` 키 보존 형태
- LangChain 표준(`page_content` + `metadata`)을 따르는지

**완료 기준**: `P1_payload.json` 캡처 + `report.md`에 키 컨벤션 1줄 명시

---

## P2. 차원 호환성 (text-embedding-3-large 3072)

```bash
# 첫 적재로 만들어진 컬렉션 차원 확인
curl http://localhost:6333/collections/tilellm | jq '.result.config.params.vectors.size'

# 새 index_name으로 3072 모델 적재
curl -X POST http://localhost:8000/api/ingestion \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "id":"poc-3l-1","type":"text","content":"3072차원 테스트",
    "namespace":"poc_3l","embedding":"text-embedding-3-large",
    "engine":{"name":"qdrant","url":"http://qdrant:6333","index_name":"tilellm_3l"}
  }'

curl http://localhost:6333/collections/tilellm_3l | jq '.result.config.params.vectors.size'
```

**완료 기준**:
- 첫 적재가 차원을 결정하는지 yes/no
- 우리가 사전 생성해야 하는지 yes/no
- 3072가 정상 만들어지면 PASS, 아니면 `text-embedding-3-small`(1536) 폴백 결정

---

## P3. Upsert + Delete

```bash
# 같은 id 재적재
curl -X POST .../api/ingestion -d '{"id":"poc-up-1","content":"버전1",...}'
curl -X POST .../api/ingestion -d '{"id":"poc-up-1","content":"버전2",...}'

# 검색으로 본문이 '버전2'인지 확인
curl -X POST http://localhost:8000/api/qa \
  -d '{"question":"버전","namespace":"poc_payload","top_k":1,"engine":{...}}'

# Tiledesk wrapper 삭제 API 시도 (정확 명칭 OpenAPI에서 확인)
curl -X POST http://localhost:8000/api/delete/id \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"id":"poc-up-1","namespace":"poc_payload"}'

# Qdrant Direct 필터 삭제 시도(우회)
curl -X POST http://localhost:6333/collections/tilellm/points/delete \
  -H "Content-Type: application/json" \
  -d '{"filter":{"must":[{"key":"metadata.tags","match":{"value":"d:www.kspo.or.kr"}}]}}'
```

**완료 기준**:
- 같은 id 재적재 = upsert (PASS) 또는 우회 시퀀스 결정
- 단건/필터 삭제 가능 여부 결정
- 키 경로(`metadata.tags` vs `tags`)는 P1 결과에 따라 조정

---

## P4. End-to-end 검색 검증

우리 Direct 어댑터로 1건을 P1에서 캡처한 키 컨벤션 그대로 적재 → `/api/qa`로 검색해서 우리 데이터가 반환되는지 확인.

```bash
# 우리 시스템(아직 코드 없음) 대신 cURL로 흉내:
# Qdrant Direct upsert (P1 키 컨벤션 그대로)
curl -X PUT http://localhost:6333/collections/tilellm/points \
  -H "Content-Type: application/json" \
  -d '{
    "points": [{
      "id": "<uuid>",
      "vector": [<3072 floats>],
      "payload": {
        "page_content": "헤더 + 본문",
        "metadata": {
          "id": "p4-1",
          "source": "https://www.kspo.or.kr/test",
          "namespace": "kspo",
          "type": "text",
          "domain_host": "www.kspo.or.kr",
          "title": "테스트",
          "tags": ["d:www.kspo.or.kr","p:2026"]
        }
      }
    }]
  }'

# Tiledesk-LLM /api/qa 검색
curl -X POST http://localhost:8000/api/qa \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "question":"테스트",
    "namespace":"kspo",
    "top_k":3,
    "engine":{"name":"qdrant","url":"http://qdrant:6333","index_name":"tilellm"}
  }'
```

**완료 기준**:
- 응답의 `sources[].source`에 우리가 적재한 URL이 등장
- 응답 텍스트가 우리가 적재한 본문을 인용

**실패 시**: 키 컨벤션을 우리가 정확히 따르지 못한 것이므로 P1 결과를 다시 검토하고 우리 어댑터의 payload 매핑을 보정.

---

## 산출물

```
poc/
├── checklist.md         # 본 파일
├── curl/
│   ├── P1_capture.sh
│   ├── P2_dim.sh
│   ├── P3_upsert.sh
│   └── P4_search.sh
├── captures/
│   ├── P1_payload.json
│   ├── P2_dims.json
│   └── ...
└── report.md            # 최종 결과 1장
```

`report.md` 표준:

```markdown
# PoC 결과 — YYYY-MM-DD

## 결정 사항
- payload 키: page_content + metadata.{...}   (예시; P1 결과)
- 임베딩 모델: text-embedding-3-large(3072) / 폴백: text-embedding-3-small
- upsert: yes
- 삭제: API={...} / Direct 필터={...}
- 검색 동작: yes (우리 데이터가 sources에 등장)

## 본 시스템 적용
- docs/design/03_chunk_embed_qdrant.md §3.9: payload 키마스 확정
- docs/design/03_chunk_embed_qdrant.md §3.5: 임베딩 모델 확정
```

이 보고서가 정리되면 본 시스템 코드(`docs/tasks/M0_T0_1.md`)에 진입.
