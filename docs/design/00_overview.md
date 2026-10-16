# 00. 개요 (Lite v2.1)

## 0.1 시스템 목적

KSPO 본사이트와 패밀리 사이트의 콘텐츠를 자동 수집·정제·벡터화하여 **Qdrant 듀얼 모드**(개발/파일럿: 자체 컨테이너 / 정식 운영: Tiledesk 외부 인스턴스)에 Direct 모드로 적재한다. 챗봇은 Tiledesk-LLM `/api/qa`로 같은 Qdrant를 검색하여 사용자에게 관련 페이지 URL과 첨부 다운로드 링크를 제시한다.

본 v2.0은 단일 Admin 내부 도구라는 운영 성격에 맞춰 v1.0(원안)을 약 절반으로 단순화한 **MVP**다. 운영하다 필요해지면 Tier 2/3 기능을 점진 추가한다(부록 §C).

## 0.2 핵심 의사결정 (요약)

| 분류 | 결정 |
|---|---|
| 언어/스택 | Python 3.12, FastAPI, ARQ + Redis, PostgreSQL 16 |
| 크롤 범위 | Admin이 등록한 도메인 호스트셋(서브도메인 포함) |
| 증분 감지 | Content Hash 기반 |
| LLM 정제 모델 | `OPENAI_REFINE_MODEL` (시작값 `gpt-5.4-mini`) |
| LLM 출력 | refined_text + is_meaningful + summary + keywords (4개 필드) |
| 임베딩 모델 | `text-embedding-3-large`(3072), PoC로 확정 |
| 벡터 DB | **Qdrant 듀얼 모드** — 개발/파일럿: 자체 컨테이너 / 정식 운영: Tiledesk 외부 인스턴스. `QDRANT_URL` 토글. Direct 모드 단일 채널 |
| Namespace | 단일 `kspo` |
| 청킹 | LONG(>800 토큰) 분할 / 그 외 단일 청크 (2단) |
| 헤더 | 고정 1종 — 제목·도메인·게시일·요약 |
| 보일러플레이트 | L1(Trafilatura) + L2(셀렉터 블랙리스트) — 자동 코퍼스 분석 미포함 |
| 첨부파일 | 다운로드 + 텍스트 추출 + `/files/{id}` |
| 관리자 | 단일, HTTP Basic Auth → 세션 |
| Admin UI | **React + TypeScript + Tailwind + shadcn/ui (SPA)** — `design-system/` 토큰 사용 |
| 컨테이너 | nginx + api + worker + postgres + redis + qdrant(개발/파일럿) — **6개**. 정식 운영 시 qdrant 제거 → 5개 |
| 배포 | Docker Compose. Tiledesk는 별도 Compose |
| 백업 | 운영하지 않음 (재크롤 복원). KSPO IT 정책 요구 시 fallback SOP는 PRD §5.4 참조 |

## 0.3 데이터 흐름

```
[적재 경로]
 Admin → nginx → FastAPI → PostgreSQL (도메인/Job/페이지/청크/첨부/llm_usage)
                       ↘ Crawler → Cleaner → Refiner → Chunker → Embedder
                                                                     ↓
                                            Qdrant (개발/파일럿: 자체 / 정식: Tiledesk)
[질의 경로]
 사용자 → Tiledesk Chatbot → /api/qa → Qdrant (벡터 검색)
                                          ↓
                              answer + sources[](URL, summary, tags)

 사용자 → nginx → /files/{id} → 본 시스템 (원본 첨부 다운로드)
```

## 0.4 본 시스템이 책임지지 않는 것

- Tiledesk 챗봇 플로우 설계
- Tiledesk-LLM 컨테이너 운영 (별도 Compose)
- Qdrant 인스턴스 자체 운영
- OpenAI 계정·요금제 관리
- 크롤 대상 사이트 저작권 검토 (Admin이 등록 시 확인)

## 0.5 NFR

| 항목 | 기준 |
|---|---|
| 크롤 처리량 | 도메인당 1~3 req/s |
| 단일 Job 최대 페이지 | 50,000 |
| LLM 정제 동시성 | 4~10 |
| 임베딩 처리량 | 50~100 chunks/sec/worker |
| 가용성 모델 | 단일 Admin · 단일 호스트 |
| 복구 | 재크롤 기반 (백업 없음) |

## 0.6 Lite 단순화 매트릭스

| 항목 | v1.0 | v2.0 (Lite) |
|---|---:|---:|
| Phase | 10 | 6 |
| PG 테이블 | 17 | 6 |
| API 엔드포인트 | 50+ | 14 |
| Admin UI 페이지 | 12 | 5 |
| ARQ 큐 | 9 | 3 |
| 컨테이너 (lite 원안) | 4 | 3 |
| 컨테이너 (v2.1 본 시스템) | — | **6**(개발/파일럿) → 5(정식) ¹ |
| LLM 출력 필드 | 8 | 4 |
| 청킹 단계 | 4단 적응형 | 2단 |
| Refresh API | 11 | 3 |

¹ Lite docx(v2.0)의 3 컨테이너 원안 대비 본 시스템(v2.1)은 nginx 분리 + Qdrant 컨테이너 추가로 6개. Qdrant는 정식 운영 시 외부 Tiledesk 인스턴스로 전환 → 5개 (PRD §6.3, §4.2).

빠진 기능은 **부록 §C Tier 2/3 로드맵** 참조. 죽은 채로 두지 않고 측정 기반 추가 시점을 명시.
