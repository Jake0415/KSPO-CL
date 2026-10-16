---
marp: true
theme: default
paginate: true
header: "kspo-ingest v2.1 인계 교육"
footer: "© 무한아이티 → KSPO"
---

# kspo-ingest

KSPO 콘텐츠 → Qdrant 벡터 KB 적재 시스템

무한아이티 → KSPO 인계 교육 (Day 1)

---

## 왜 이 시스템인가?

- KSPO 사이트에 흩어진 정보 — 사이트 검색·FAQ만으로 한계
- Tiledesk 챗봇이 정확한 답변 + 출처(URL)를 제공해야
- → KB 적재 파이프라인 없으면 챗봇 답변 품질 저하

**목표**: 본사이트 + 패밀리 사이트 → 매주 자동 갱신

---

## 4 KPI

| KPI | 목표 |
|---|---|
| 적재 커버리지 | ≥ 90% |
| 적재 신선도 | ≤ 7일 |
| Job 성공률 | ≥ 95% |
| 월 LLM 비용 | ≤ 150,000원 |

`scripts/kpi_measure.py`로 자동 측정.

---

## 시스템 구성 (7 컨테이너)

```
nginx ─┬─ web (Next.js Admin UI :3300)
       └─ api (FastAPI :8080) ─┬─ postgres
                                ├─ redis
                                └─ qdrant *
worker (ARQ) ─────────────────────┘
```

`*` 정식 운영 시 Tiledesk 외부로 전환 → 6 컨테이너

---

## 한 페이지의 여정

```
URL → fetch → clean → (hash 같으면 skip)
                    → refine (gpt-5.4-mini)
                    → chunk → embed (text-embedding-3-large)
                    → Qdrant upsert → INDEXED
```

- **Hash skip** = LLM 비용 0 (incremental의 핵심)
- **차원 3072** = `text-embedding-3-large`

---

## Qdrant 듀얼 모드

| 단계 | QDRANT_URL | 설명 |
|---|---|---|
| 개발/파일럿 | `http://qdrant:6333` | 자체 컨테이너 |
| 정식 운영 | KSPO·Tiledesk 제공 | 외부 인스턴스 |

**전환 절차** = `.env` 변경 + `docker compose restart api worker` (코드 분기 없음)

---

## 다음 슬라이드

1. **`00_intro.md`** ← 지금
2. `01_admin_daily.md` — Admin 매일·매주 일과
3. `02_runbook_walkthrough.md` — 런북 A/B/C 시연
4. `03_qna.md` — Q&A 준비

---

## 질문 받습니다

이번 슬라이드 (시스템 개요)에 대한 질문 5분.

다음: Admin 일과
