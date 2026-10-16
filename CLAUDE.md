# KSPO 웹크롤링 → Qdrant 적재 시스템 (Lite v2.0)

## 프로젝트 개요

KSPO 본사이트와 패밀리 사이트를 자동 수집·정제·벡터화하여 **Tiledesk가 운영하는 Qdrant**에 Direct 모드로 적재한다.
**Lite 버전(v2.0)**은 단일 Admin 내부 도구라는 운영 성격에 맞춰 v1.0의 약 절반 분량으로 단순화한 MVP다.
Tier 2/3 기능(카테고리·룰엔진·보일러플레이트 자동분석·SimHash·SSE 등)은 운영 후 필요해지면 추가한다.

---

## 1차 자료 (단일 진실원, 우선순위 순)

1. `poc/report.md` — PoC 결과(있을 때 가장 우선)
2. `docs/tasks/M{n}_T{n.m}.md` — 현재 진행 Task 지시서
3. `docs/design/00_overview.md` ~ `05_devops_ops.md` — Phase별 Markdown
4. `docs/design/_appendix.md` — DDL 6테이블, ARQ Task, 운영 런북, Tier 2/3 로드맵
5. `design-system/` — Admin UI 시각 어휘 (CLAUDE.md → DESIGN_SYSTEM.md → COMPONENTS.md → PATTERNS.md → tokens/)
6. `통합설계서_v2.0.docx` — 기준 문서 (Markdown과 충돌 시 Markdown 우선)

---

## 핵심 결정 (변경 시 반드시 사용자 확인)

- 언어/스택: Python 3.12 / FastAPI / ARQ + Redis / PostgreSQL 16
- 벡터 DB: **Qdrant 듀얼 모드** — 개발/파일럿은 자체 컨테이너, 정식 운영은 Tiledesk 외부 인스턴스. `QDRANT_URL` 환경변수만 토글 (PRD §4.2). **Direct 모드** 적재 (PRD §4.3)
- Tiledesk-LLM `/api/ingestion`은 사용하지 않는다 (Tiledesk-LLM은 본 Compose에 미포함)
- 컨테이너 구성: nginx + web(Next.js) + api + worker + postgres + redis + qdrant(개발/파일럿) — **7개**, 정식 운영 전환 시 qdrant 제거하여 6개 (PRD §6.3)
- Namespace: 단일 `kspo`. 도메인은 payload `tags`(`d:<host>`)로 구분
- 임베딩 모델: `text-embedding-3-large`(3072) 우선, PoC 결과로 확정
- 정제 모델: 환경변수 `OPENAI_REFINE_MODEL` (시작값 `gpt-5.4-mini`)
- 인증: 단일 Admin, HTTP Basic Auth → 세션
- **Admin UI: Next.js 16 (App Router, standalone) + React 19 + Tailwind 3 + shadcn/ui + lucide-react** — Node 서버로 실행, nginx가 reverse proxy. Jinja2/HTMX 미사용, FastAPI는 API만 제공
- 시각 어휘: `design-system/` 토큰·컴포넌트만 사용 (Primary `#155DFC`, 카드 radius 12, 보더 `#E2E8F0` 등 — `design-system/CLAUDE.md` 참조)
- 백업: 별도 보관 운영하지 않음. 손실 시 재크롤·재정제·재임베딩으로 복원
- 청킹: **2단** — LONG(>800 토큰) 분할 / 그 외 단일 청크
- 컨텍스트 헤더: 고정 1종 (제목 + 도메인 + 게시일 + 요약)
- 보일러플레이트 제거: L1(Trafilatura) + L2(셀렉터 블랙리스트)만
- 카테고리: Tier 1 미포함 — keywords로 챗봇 필터링
- 첨부파일: 다운로드 + 텍스트 추출 + `/files/{id}` 공개 엔드포인트

---

## 코딩 규칙

- 비동기 일관: asyncio + httpx + asyncpg + arq
- ORM: SQLAlchemy 2.0 async
- 검증: Pydantic v2, Settings는 pydantic-settings
- 로깅: loguru JSON 1줄/이벤트, 본문 텍스트 미포함, 키 마스킹
- 테스트: pytest + pytest-asyncio. **신규 백엔드 모듈은 단위 테스트 동반 (>80% 라인 커버리지)**. UI(`web/`)는 lint + TypeScript 컴파일 + 수동 검증, e2e 자동화는 M5에서 도입
- lint: ruff (line 100), formatter: ruff format
- import: `from __future__ import annotations`, 절대 import

---

## 작업 단위 규약

- 1 PR ≈ 1 Task (`docs/tasks/` 한 파일)
- PR 본문에 다음 4줄: `Closes`, `Summary`, `Test`, `Risk`
- 마이그레이션 추가 시 Alembic revision id 명시
- 새 환경변수 추가 시 `.env.example` 갱신
- 외부 의존성 추가는 `pyproject.toml` 한 곳에만

---

## 절대 금지

- Tiledesk-LLM `/api/ingestion` 호출 코드 추가 (Direct 모드 단일 채널)
- 임베딩 모델 하드코딩 (환경변수 우선)
- 원본 본문 텍스트의 로그 출력 (길이/해시/tokens만)
- 시크릿 git 커밋
- 백업 인프라 추가 (설계 결정 위반)
- **Tier 2/3 기능을 미리 구현 — `_appendix.md` 마지막의 Tier 표를 참고하고, MVP 범위 외는 보류**
- **`design-system/` 외부의 컬러/radius/shadow 임의 사용 금지** — Primary `#155DFC` 외 컬러는 사전 합의 필수, 카드 radius는 항상 12, shadow는 floating element(modal/dropdown/toast)에만
- Jinja2 / HTMX / FastAPI 측 SSR 템플릿 도입 (Admin UI는 Next.js로 일원화 — FastAPI는 API만 제공)

---

## 빠른 참조

| 영역 | 위치 |
|---|---|
| Compose · Dockerfile | `docs/design/05_devops_ops.md` §5.1 |
| API 카탈로그(14개) | `docs/design/04_incremental_admin.md` §4.5 |
| DDL 통합(6 테이블) | `docs/design/_appendix.md` §A |
| Tier 2/3 로드맵 | `docs/design/_appendix.md` §C |
| 환경변수 | `.env.example` |
| 운영 런북(3종) | `docs/design/_appendix.md` §B |
| PoC(4 항목) | `poc/checklist.md` |
| 디자인 시스템 진입점 | `design-system/CLAUDE.md` |
| 디자인 토큰 (CSS 변수) | `design-system/tokens/tokens.css` |
| Tailwind 설정 | `design-system/tokens/tailwind.config.js` |
| AppShell 레퍼런스 | `design-system/examples/AppShell.tsx` |

---

## 다음에 일어날 일

`docs/tasks/M0_T0_1.md`부터 시작. Task가 PR 한 개에 대응.
PoC가 진행 중이면 `poc/report.md`를 먼저 갱신하고 본 코딩에 진입.
마일스톤: M0(부트스트랩) → M1(데이터모델+Admin) → M2(파이프라인) → M3(임베딩+적재) → M4(증분) → M5(운영).

---

# 부록 — 일반 코딩 행동 가이드

> 이하는 프로젝트 무관 LLM 코딩 실수 방지용 일반 원칙. 위의 프로젝트 헌법과 충돌 시 **위의 결정이 우선**한다.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
