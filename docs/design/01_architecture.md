# 01. 전체 아키텍처

## 1.1 컴포넌트 토폴로지

```
┌──────── Docker Compose : kspo-ingest ────────┐
│  nginx (host 80/443)                          │
│   ├─ SPA dist (React + Tailwind)              │
│   ├─ /api/* → api 리버스 프록시              │
│   └─ /files/{id} → api 리버스 프록시         │
│                                                │
│  api (FastAPI — REST API only)                │
│   ├─ /api/* (도메인/Job/페이지)               │
│   └─ /files/{id} (첨부 다운로드 스트리밍)    │
│                                                │
│  worker (단일 ARQ 워커)                       │
│   └─ 큐 3종: default / attach / bg            │
│                                                │
│  postgres / redis                             │
│  qdrant ¹ (개발/파일럿 전용 — 정식 시 제거)  │
└───────────────────────────────────────────────┘
              │ Direct write (QDRANT_URL)
              ▼
┌──── 정식 운영 시 : 별도 Compose : tiledesk ────┐
│  qdrant ◀── /api/qa 검색 ◀── tilellm           │
└─────────────────────────────────────────────────┘

      OpenAI ◀── (HTTPS_PROXY 경유) Refiner / Embedder
```

¹ **Qdrant 듀얼 모드**: 개발/파일럿 단계는 본 Compose의 `qdrant` 컨테이너에 적재. 정식 운영 진입 시 `qdrant` 서비스 종료 + 볼륨 삭제, `QDRANT_URL`을 Tiledesk 외부 인스턴스로 변경. 전환 절차는 PoC P1~P4 재검증 의무 (PRD §4.2).

## 1.2 외부 의존성

| 외부 시스템 | 용도 | 인터페이스 | 위치 |
|---|---|---|---|
| OpenAI | LLM 정제 + 임베딩 직접 호출 | openai SDK | 외부 (`HTTPS_PROXY` 경유) |
| Qdrant (자체) | 벡터 적재·검증 | qdrant-client | 본 Compose 내부 (개발/파일럿) |
| Qdrant (Tiledesk) | 벡터 적재(우리)·검색(Tiledesk) | qdrant-client | 외부 (정식 운영 시 전환) |
| Tiledesk-LLM | 챗봇 검색 (본 시스템은 호출 안 함) | (미사용) | 외부 — 별도 Compose |

## 1.3 모듈 인터페이스

```python
crawl(url)      -> RawPage{url, html, http_meta}
clean(raw)      -> CleanedPage{title, body_text, meta, content_hash, attachments[]}
refine(cleaned) -> RefinedPage{refined_text, is_meaningful, summary, keywords}
chunk(refined)  -> List[Chunk{chunk_id, text, position}]
embed(chunks)   -> List[EmbeddedChunk{..., vector}]
upsert(emb)     -> UpsertResult{indexed, failed}
```

## 1.4 페이지 상태 전이

```
DISCOVERED → FETCHED → CLEANED → REFINED → INDEXED
                                   ↘ DROPPED (의미없음/비한국어/빈본문)
   ↘ ERROR (영구 실패)
   ↘ REMOVED (3회 연속 404)
```

## 1.5 ARQ 큐 (3개)

```
queue:default   crawl, clean, refine, embed, upsert (단일 체인)
queue:attach    첨부 다운로드 + 텍스트 추출
queue:bg        주간 incremental, 정기 cleanup
```

워커 1개가 모두 처리. 동시성은 환경변수 `WORKER_CONCURRENCY`.

## 1.6 보안·운영

- **외부 노출은 `nginx`만** (host 80/443). `api`(8080)·`postgres`·`redis`·`qdrant`(6333)는 compose 내부 네트워크 only
- TLS 종료: nginx 컨테이너 (사내 인증서 마운트 — KSPO IT가 외부 LB 종료 선호 시 변경 가능)
- Admin: HTTP Basic Auth → 세션 쿠키 (bcrypt cost ≥ 12). 세션 만료 8시간
- `/files/{id}`: 공개 (인증 없음, Referer 화이트리스트는 옵션)
- 시크릿: `.env` chmod 600, git 미포함
- 모든 외부 API TLS 검증 활성

## 1.7 v2.0에서 빠진 것 (Tier 2/3 이동)

- `worker-backfill` / `scheduler` 별도 컨테이너 (단일 worker로 통합)
- `audit_log`/`page_history`/`dead_jobs`/`alerts` 테이블 (로그 파일·`crawl_jobs.stats`로 흡수)
- Prometheus exporter (PG select로 충분)
- SSE 실시간 로그 (5초 폴링으로 대체)

부록 §C 참조.
