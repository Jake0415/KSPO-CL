# PoC 결과 — 2026-07-04

> 본 보고서는 P1~P4 실행 후 작성. 단일 진실원.

---

## 0. 환경

| 항목 | 값 |
|---|---|
| 실행 일자 | 2026-07-04 |
| Tiledesk-LLM | 로컬 빌드 (gunicorn 부트 실패 → Qdrant Direct 우회) |
| Qdrant 이미지 | `qdrant/qdrant:latest` |
| 컬렉션 이름 | `tilellm` |
| 위치 | 로컬 docker compose (tiledesk-llm-poc) |

---

## 1. 결정 사항

### payload 키 컨벤션 (P1) ✅

```
본문 텍스트 키:  page_content
메타 위치:        metadata.{...} 중첩
보존되는 키:      id, source, namespace, type, domain_host, title, summary, keywords, posted_at, tags, ...
LangChain 표준:   일치
```

→ `build_payload()` 출력과 **완전 일치**. 변경 불필요.

캡처 결과: `poc/captures/P1_payload.json`

### 임베딩 모델 / 차원 (P2) ✅

| 항목 | 값 |
|---|---|
| 사전 컬렉션 생성 필요 | **yes** (bootstrap.py `managed` 모드로 처리) |
| `text-embedding-3-large` (3072) 정상 생성 | **PASS** |
| 본 시스템 사용 모델 (확정) | `text-embedding-3-large` (3072) |

### Upsert · Delete (P3) ✅

| 동작 | 결정 |
|---|---|
| 같은 UUID point_id 재적재 → upsert | **PASS** (포인트 수 2 유지, 내용 업데이트 확인) |
| Qdrant Direct 필터 삭제 | **PASS** (`metadata.tags` match `d:www.kspo.or.kr` → 2건 삭제, 잔여 0) |
| 본 시스템 삭제 경로 (확정) | **Qdrant Direct 필터** |

### E2E 검색 (P4) ✅

| 항목 | 결과 |
|---|---|
| 검색 방식 | Qdrant `/points/search` (cosine similarity) |
| 쿼리 | "올림픽공원이 어디에 있나요?" |
| 1위 | Score=**0.6416** — 올림픽공원 운영 안내 (`/olympicpark/guide`) |
| 2위 | Score=**0.2116** — 경륜·경정 사업 소개 (`/business/cycle`) |
| 우리 데이터 검색 | **PASS** |
| 랭킹 정확도 | **PASS** (관련 문서 1위, 점수 차 0.43) |

---

## 2. 본 시스템 적용 사항

| 본 시스템 위치 | 변경 |
|---|---|
| `src/kspo_ingest/qdrant/payload.py` `build_payload()` | **변경 불필요** — 현행 유지 |
| `settings.py` `openai_embed_model` | `text-embedding-3-large` 확정 |
| `settings.py` `qdrant_index_name` | `tilellm` 확정 |
| `qdrant/adapter.py` 삭제 경로 | Qdrant Direct 필터 (`metadata.tags`) |

---

## 3. 정식 운영 전환 체크리스트 (PRD §4.2)

본 PoC 결과는 **정식 운영 전환 시점에 의무 재검증** 대상.

- [ ] P1 재검증 — Tiledesk 측 컬렉션 payload 키
- [ ] P2 재검증 — 차원 호환성
- [ ] P3 재검증 — upsert / delete
- [ ] P4 재검증 — E2E 검색
- [ ] 자체 `qdrant` 컨테이너 종료 + 볼륨 삭제
- [ ] `full` Job 재실행으로 Tiledesk 컬렉션 채우기

---

## 4. 변경 이력

| 일자 | 변경 |
|---|---|
| 2026-07-04 | 초판 — P1~P4 결과 작성. Qdrant Direct 검증. 전항목 PASS |
