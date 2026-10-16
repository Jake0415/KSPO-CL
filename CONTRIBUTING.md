# 기여 가이드

## 작업 단위

- 1 PR = 1 Task (`docs/tasks/M{n}_T{n.m}.md` 한 개)
- PR 본문: `Closes` / `Summary` / `Test` / `Risk` 4줄
- 새 환경변수 추가 시 `.env.example` 갱신
- 새 의존성은 한 곳에만 — 백엔드는 `pyproject.toml`, 프론트엔드는 `web/package.json`

## 코딩 규칙

### 백엔드 (Python)

- Python 3.12, async 일관 (`asyncio` + `httpx` + `asyncpg` + `arq`)
- ORM: SQLAlchemy 2.0 async
- 검증: Pydantic v2, Settings는 pydantic-settings
- 로깅: loguru JSON 1줄/이벤트, 본문 텍스트 미포함, 키 마스킹
- 테스트: pytest + pytest-asyncio. **신규 백엔드 모듈은 단위 테스트 동반 (>80% 라인 커버리지)**
- lint: `ruff check src tests`, formatter: `ruff format src tests` (line 100)
- import: `from __future__ import annotations`, 절대 import

### 프론트엔드 (`web/`)

- React 18 + TypeScript + Tailwind CSS + shadcn/ui (Radix 기반) + lucide-react
- 빌드: Vite. 라우터: React Router v6. 데이터 페칭: TanStack Query
- 시각 어휘는 `design-system/` 단일 진실원
  - Primary `#155DFC`, 카드 `border-radius: 12px`, 보더 `#E2E8F0`
  - 임의 컬러/radius/shadow 추가 금지 (`design-system/CLAUDE.md` 절대 금지 §10 참조)
- 검증: lint(ESLint) + TypeScript 컴파일 + 수동 검증. e2e 자동화는 M5.T5.2

## 마이그레이션

- Alembic revision id 명시 (예: `0002_core_tables`)
- 운영: `docker compose --profile migrations run --rm migrations`
- 개발: `ALEMBIC_AUTO=true`로 자동
- 새 마이그레이션 추가 시 PR 본문에 revision id 명시

## 보안

- `.env`는 git 미포함, `chmod 600`
- `ADMIN_PASSWORD_BCRYPT`는 운영 호스트에서 생성:
  ```sh
  python -c "from passlib.hash import bcrypt; import getpass; print(bcrypt.using(rounds=12).hash(getpass.getpass('Admin password: ')))"
  ```
- 본문 텍스트는 로그 출력 금지 (길이/해시만)

## 절대 금지 (v2.1)

- Tiledesk-LLM `/api/ingestion` 호출 코드 추가 (Direct 모드만)
- 임베딩 모델 하드코딩 (환경변수 우선)
- 시크릿 git 커밋
- Tier 2/3 기능을 미리 구현 (`docs/design/_appendix.md` §C 참조)
- Jinja2 / HTMX / SSR 템플릿 도입 (Admin UI는 React SPA)
- `design-system/` 외부 컬러/radius/shadow 임의 사용

## 참고

- 프로젝트 헌법: [`CLAUDE.md`](./CLAUDE.md)
- 로드맵: [`docs/tasks/00_roadmap.md`](./docs/tasks/00_roadmap.md)
- PRD 인덱스: [`docs/prd/00_index.md`](./docs/prd/00_index.md)
- 디자인 시스템: [`design-system/CLAUDE.md`](./design-system/CLAUDE.md)
