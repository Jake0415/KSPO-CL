# PRD §4 — 솔루션 개요

> 본 파일: PRD **§4**. 전체 인덱스: [00_index.md](./00_index.md)
> 작성: 2026-05-07 / 상태: draft v1.4

---

## 4. 솔루션 개요

### 4.1 데이터 흐름

```
Admin → FastAPI → PostgreSQL
                ↘ Crawler → Cleaner → Refiner → Chunker → Embedder
                                                              ↓
                                                  Qdrant (듀얼 모드)
```

자세한 단계별 책임·테이블은 `docs/design/00_overview.md`, `01_architecture.md` 참조.

### 4.2 Qdrant 듀얼 모드 ✓

| 단계 | Qdrant 위치 |
|---|---|
| 개발 / 테스트 / PoC / 파일럿 | **자체 컨테이너** (kspo-ingest Compose 내) |
| 정식 운영 | **Tiledesk 외부 인스턴스** — `QDRANT_URL` 환경변수 토글 |

전환 조건:
- 파일럿 완료 후 정식 운영 진입 시 ✓
- Tiledesk 컬렉션 빈 상태 → `full` Job 재실행으로 채움 ✓
- PoC P1~P4 재검증 의무 ✓
- 자체 Qdrant 컨테이너는 종료 + 볼륨 삭제 ✓

### 4.3 핵심 기술 결정 (요약)

| 항목 | 결정 | 출처 |
|---|---|---|
| 언어/스택 | Python 3.12 / FastAPI / ARQ + Redis / PostgreSQL 16 | docx §0.2 |
| Admin UI | React 18 + TypeScript + Tailwind + shadcn/ui (SPA) | `docs/design/04` §4.7 |
| 임베딩 | `text-embedding-3-large` (3072 dims), PoC로 확정 | docx §0.2 |
| 정제 | `OPENAI_REFINE_MODEL` (시작값 `gpt-5.4-mini`) | docx §0.2 |
| 청킹 | 2단 (>800 토큰 분할 / 그 외 단일) | docx §0.2 |
| 적재 모드 | Qdrant Direct (Tiledesk-LLM `/api/ingestion` 미사용) | docx §0.2 |

---

이전: [§2 이해관계자·§3 범위](./03_stakeholders_scope.md) · 다음: [§5 NFR·§6 인프라](./05_nfr_infra.md)
