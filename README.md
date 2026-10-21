# KSPO Ingest — 독립 로컬 프로젝트

로컬 실행은 [LOCAL_SETUP.md](LOCAL_SETUP.md)를 참조하세요. 기본 명령은 `docker compose up -d --build`이며 콘솔은 http://localhost:3334 입니다. 로그인 정보는 비공개 `LOCAL_ACCESS.txt`에 있습니다. 운영 Sonar 연결 및 자동 스케줄은 기본으로 비활성화되어 있습니다.

---

아래는 원본 프로젝트의 참고 문서입니다. Docker 경로와 운영 서버 설정은 로컬 실행 가이드보다 우선하지 않습니다.

# kspo-ingest (Lite v2.1)

KSPO 웹크롤링 → Qdrant 벡터 DB 적재 시스템. Tiledesk 챗봇 연동용 데이터 수집·정제·벡터화 백엔드의 **단순화 MVP 버전**.

> v1.0(원안) 대비 Phase·테이블·API·UI 페이지를 약 절반으로 줄이고, 운영 후 필요해지면 추가하는 점진적 확장 구조를 채택했다.

## 빠른 시작 (새 PC에서 처음 받았을 때)

> `.env`는 보안상 git에 포함되지 않습니다 — 별도 채널로 전달받은 값으로 직접 작성.

```bash
# 1) clone
git clone https://github.com/Jake0415/kspo-ingest.git
cd kspo-ingest

# 2) .env 작성 (.env.example을 복사 후 실값 입력)
cp .env.example .env
#  필수 키: ADMIN_USERNAME, ADMIN_PASSWORD_BCRYPT, SESSION_SECRET,
#           POSTGRES_PASSWORD, OPENAI_API_KEY
#
# bcrypt 해시 생성 (Python 3.12+):
#   python -c "import bcrypt, getpass; \
#     print(bcrypt.hashpw(getpass.getpass('pw: ').encode(), bcrypt.gensalt(12)).decode())"
# SESSION_SECRET 생성:
#   python -c "import secrets; print(secrets.token_hex(32))"

# 3) 6 services 기동 (Qdrant는 외부 Tiledesk 인스턴스 사용 — 로컬 qdrant 컨테이너 없음)
#    .env의 QDRANT_URL이 외부 Qdrant를 가리켜야 하며, 해당 호스트에 네트워크 접근이 필요.
docker compose -f docker/docker-compose.yml up -d postgres redis
docker compose -f docker/docker-compose.yml --profile migrations run --rm migrations
docker compose -f docker/docker-compose.yml up -d api worker web nginx

# 4) 접속
curl http://localhost/healthz       # → 200
curl http://localhost/readyz        # → 200 (db/redis/qdrant_dim/qdrant_mode/proxy/cost)
open http://localhost/docs          # Swagger UI (FastAPI)
open http://localhost/              # Admin UI (Next.js 16)
```

새 PC에서 단위 테스트만 돌리려면:
```bash
uv sync                              # .venv + 의존성 (uv.lock 기반)
uv run pytest -q                     # 160 단위 테스트
cd web && npm ci && npm run build    # 프론트엔드 빌드 검증
```

> Qdrant는 Tiledesk 외부 인스턴스를 사용한다 (`.env`의 `QDRANT_URL`). 로컬 `qdrant` 서비스는 compose에서 제거됨 (6 services). 모드는 `QDRANT_URL`로 자동 판별 — `"qdrant"` 문자열 포함 시 self_hosted, 그 외 external. PoC P1~P4 재검증 의무 (PRD §4.2).

## Claude Code에 작업 위임

```
Read CLAUDE.md and docs/tasks/M{n}_T{n.m}.md, then implement that task.
Open a PR when ready with summary, test, risk in the PR body.
```

24 Task 모두 [`docs/tasks/`](./docs/tasks/)에 명세 작성 완료.

## 디렉토리

```
.
├── CLAUDE.md              # 프로젝트 헌법 (단일 진실원)
├── CONTRIBUTING.md        # 기여 가이드 (1 PR = 1 Task)
├── README.md
├── pyproject.toml
├── .env.example
├── .github/               # CI workflow + PR template
├── docs/
│   ├── prd/               # PRD (8 파일 — 인덱스: 00_index.md, v1.5)
│   ├── design/            # Phase별 Markdown (00 ~ 05 + 부록)
│   ├── tasks/             # 24 Task + 로드맵 (M0~M5)
│   ├── runbook/           # 운영 런북 3종 (A/B/C)
│   └── handover/          # KSPO 외부 부서 송부용 질의서
├── design-system/         # 시각 토큰·컴포넌트 카탈로그 (단일 진실원)
├── poc/                   # PoC 4 항목 + curl 스크립트 + report 템플릿
├── src/kspo_ingest/       # 백엔드 코드 (M0.T0.1, M0.T0.2 머지 완료)
├── tests/
├── migrations/            # Alembic
├── docker/                # Dockerfile 4종 + compose 6 services + nginx (Qdrant 외부 Tiledesk)
└── web/                   # Admin UI (Next.js 16, App Router, standalone)
```

## 마일스톤 (Lite v2.1)

| M | 내용 | Task 수 |
|---|---|---|
| M0 | 부트스트랩 (Docker, Alembic, /healthz·/readyz, CI, frontend bootstrap) | 4 |
| M1 | 데이터 모델(6 테이블) + Admin 골격 + 도메인 CRUD | 5 |
| M2 | Crawl + Clean + Refine 파이프라인 | 4 |
| M3 | Chunk + Embed + Qdrant Direct + 첨부 | 4 |
| M4 | Incremental + Manual Refresh + 주간 cron | 3 |
| M5 | 운영 (로깅·테스트·문서·런북) + 인수 | 4 |

총 **24 Task**. 단계 의존성: PoC → M0 ~ M5 → 파일럿 → 정식 전환 (Tiledesk Qdrant). 자세한 설명은 [`docs/tasks/00_roadmap.md`](./docs/tasks/00_roadmap.md).

## 운영 자료

- **운영 매뉴얼** ([`docs/operations/`](./docs/operations/)):
  - [00. 시스템 개요](./docs/operations/00_overview.md)
  - [01. Admin 일과](./docs/operations/01_admin_workflow.md)
  - [02. KSPO IT 운영 작업](./docs/operations/02_kspo_it_workflow.md)
  - [03. 자주 발생하는 문제](./docs/operations/03_troubleshooting.md)
  - [04. 인수 체크리스트](./docs/operations/04_handover_checklist.md)
- **교육 슬라이드** (marp Markdown — [`docs/training/`](./docs/training/)):
  - [00. 시스템 소개](./docs/training/00_intro.md)
  - [01. Admin 일과 시연](./docs/training/01_admin_daily.md)
  - [02. 런북 시연](./docs/training/02_runbook_walkthrough.md)
  - [03. Q&A 20선](./docs/training/03_qna.md)
- **운영 런북** (3종, 사고 대응):
  - [A. KB 차원 mismatch](./docs/runbook/A_kb_dim_mismatch.md)
  - [B. OpenAI 호출 실패 (인증·결제 분기)](./docs/runbook/B_openai_failure.md)
  - [C. Tiledesk 다운](./docs/runbook/C_tiledesk_down.md)
  - [배포 런북 (clean install / 업데이트 / 롤백)](./docs/runbook/deploy.md)
- **KSPO 외부 의사결정**: [`docs/handover/kspo_questions_v1.md`](./docs/handover/kspo_questions_v1.md) (PRD §9.3 10건을 부서별 재구성)

### PDF 빌드

운영 매뉴얼 + 교육 슬라이드를 PDF로 묶어 인계 산출물 생성.

```bash
# 운영 매뉴얼 PDF (pandoc + xelatex 필요)
make pdf
#   → dist/kspo-ingest_운영매뉴얼_v2.1.pdf

# 교육 슬라이드 PDF (marp-cli — Node.js 필요, npx로 자동 다운로드)
make training-pdf
#   → dist/training/{00_intro,01_admin_daily,02_runbook_walkthrough,03_qna}.pdf
#   → dist/training/kspo-ingest_교육슬라이드_v2.1.pdf  (합본)

# 둘 다
make docs
```

> 빌드 도구 미설치 환경에서는 markdown 직접 사용. PDF는 KSPO 인계용 산출물 — 운영 자체에는 markdown 충분.

## PoC

본격 운영 전환 전 `poc/checklist.md` 4 항목(P1~P4)을 Tiledesk Qdrant 호환성 검증으로 실행. 결과는 [`poc/report.md`](./poc/report.md) 1장으로 정리. 실행 가이드는 [`poc/README.md`](./poc/README.md).

> 파일럿까지는 자체 Qdrant 컨테이너로 진행 가능. 정식 전환 직전 P1~P4 재검증 의무 (PRD §4.2).

## v1.0 대비 단순화

- Phase: 10 + 부록 → **6**
- PG 테이블: 17 → **6**
- API: 50+ → **14**
- Admin UI: 12 페이지 → **5** (Next.js 16, App Router)
- ARQ 큐: 9 → **3**
- 컨테이너: 4 → **6** — nginx 추가, Qdrant는 외부 Tiledesk 인스턴스 사용 (로컬 컨테이너 없음)
- LLM 출력 필드: 8 → **4**
- 청킹: 4단 적응형 + 헤더 3종 → **2단 + 헤더 1종**

빠진 기능은 [`docs/design/_appendix.md`](./docs/design/_appendix.md) §C "Tier 2/3 로드맵"에서 운영 측정 기반으로 추가 시점 정의.

## 단일 진실원

| 영역 | 위치 |
|---|---|
| 프로젝트 결정 (변경 시 사용자 확인) | [`CLAUDE.md`](./CLAUDE.md) |
| 사업 의도·범위·NFR·인프라 | [`docs/prd/00_index.md`](./docs/prd/00_index.md) |
| 기술 설계 (Phase별) | [`docs/design/`](./docs/design/) |
| Task 명세 (1 PR = 1 Task) | [`docs/tasks/`](./docs/tasks/) |
| 시각 어휘 | [`design-system/CLAUDE.md`](./design-system/CLAUDE.md) |
| DDL · 런북 · Tier 2/3 로드맵 | [`docs/design/_appendix.md`](./docs/design/_appendix.md) |


## 소마 목록·상세·지도 팝업 수집

소마(`soma.kspo.or.kr`)는 일반 링크 외에 전시 연도 선택, 목록 폼의 숨김 입력값,
작가별 작품 목록, 조각공원 6개 구역의 추가 목록, 지도 핀의 `/piece/product/{id}/pop`
응답을 탐색한다. 공개 정보의 조회만 수행하며 로그인·신청·변경 동작은 실행하지 않는다.
팝업 본문과 상세 페이지의 표, 이미지 URL/alt, 첨부파일명/URL을 보존한다.
PDF 등 첨부 본문은 다운로드하거나 추출하지 않는다.

게시판 글(customer/notice, draw/notice 및 일반 게시판)은 기본 90일 기준으로 제외한다.
전시·작품·작가·교육·정적 안내에는 게시판 날짜 제한을 적용하지 않는다.
게시일을 확인할 수 없는 글은 유지한다. 전체·증분·미수집 보충 경로에 동일한 판정을 적용한다.
본문이 변하지 않아도 링크와 첨부 탐색은 실행한다.

일반 링크의 페이지당 200개 절단은 제거했다. 도메인의 max_pages/max_depth,
robots, 월 예산 제한은 유지하므로 전체 실행 결과의 미수집/실패 건수도 확인해야 한다.
실제 API·DB·SONAR를 포함한 전체 수집 검증은 배포 환경에서 별도로 실행한다.
이 변경은 임베딩 모델이나 운영 지식베이스의 차원을 변경하지 않는다.

### RAG 텍스트 정제

추출 후 NFC 문자 정규화, 불필요한 공백·제로폭 문자·조회수·닫기 등의 표시 문구와
인접 중복 줄을 제거합니다. 표의 항목/값, 작품 정보, 날짜·수치·조건과 URL은 보존합니다.
소마 작품 상세/팝업도 LLM 정제·검색 보강을 수행하며, 정제에는 전체 사실과
첨부 메타데이터를 보존하도록 지시하고 누락된 이미지/첨부 URL을 다시 추가합니다.
SONAR에는 제목·출처 URL·요약·정제 본문을 전달하고 청킹은 SONAR 설정을 따릅니다.
로컬 page.json에는 source_url, attachments, preprocessing_version도 기록합니다.
정제 버전과 제목이 변경 감지 해시에 포함되므로 다음 재수집 때 기존 문서도 재가공됩니다.
코드 배포만으로 저장된 기존 문서가 자동 재가공되지는 않으며 재수집 작업이 필요합니다.

정제 사전 제외 기준은 양끝 공백을 제외한 본문 10자 미만입니다.
한국어 비율은 기록만 하며 제외 조건과 품질 점수 감점에 사용하지 않습니다.
오류 페이지·빈 목록·Q4 제외와 게시판 90일 제한은 유지됩니다.

LLM의 is_meaningful=false는 제외 사유로 사용하지 않습니다. 정제 결과와 별도로
원문 정보도 보존하고 [LLM 정제·검색 보강] 구역을 구분합니다. LLM은 원문에 근거한
설명 문장·검색 표현·답변 가능한 예상 질문을 추가하며 외부 사실을 생성하지 않도록
지시합니다. 실제 LLM 생성 품질은 운영 샘플 검토가 필요합니다.

수치 정제: 날짜 2026-10-12는 2026년 10월 12일, 연령 10~15세는
10세부터 15세까지, 시간 09:30~18:00은 9시 30분부터 18시 0분까지로 변환합니다.
범위 기호(~, -, ～, ∼, – 등), 퍼센트, 금액 천 단위 쉼표와 수량의 소수 표기도
자연어로 정규화합니다. URL·파일명·전화번호·이메일과 확인되지 않은 식별자 표기는
원형을 유지합니다. 원시 HTML 및 구조화 메타데이터는 원본 보존용으로 변경하지 않습니다.

### 외부 링크·SNS 수집

설정된 원본 도메인에서 직접 연결한 공개 HTML 페이지를 한 단계 수집합니다.
외부 문서는 같은 원본 도메인의 작업/예산/깊이 제한을 따르며 외부 문서의 링크는
재귀 탐색하지 않습니다. 공유·로그인·삭제·구독 링크와 파일은 별도 처리하거나 제외합니다.
외부 요청은 쿠키를 공유하지 않는 HTTP 클라이언트로 수행하며 공개 주소/DNS 및
리다이렉트 목적지를 확인하고 HTML 2 MiB, 리다이렉트 6회 제한을 적용합니다.
부모 문서에는 연결 설명과 URL, 외부 문서에는 연결한 원문 페이지와 공개 OG 설명을
보존합니다. SONAR 출처/도메인 태그는 실제 외부 문서 URL을 사용합니다.
SNS가 로그인이나 접근 차단을 요구하면 우회하지 않습니다. 공개 본문 확보에 실패해도
부모 문서의 링크 메타데이터는 유지하며 그 링크를 게시물 본문으로 간주하지 않습니다.

영문 페이지 제외: 추출한 원본 본문의 Unicode 문자 중 영문 알파벳 비율이
90% 이상이면 english_majority로 제외합니다. 숫자·공백·기호·URL·파일명은 비율에서
제외하며 한국어 보강 문구를 추가하기 전에 판정합니다. 한글 비율 자체로는 제외하지
않으므로 영어가 적은 다른 언어 문서는 수집합니다. 제외 사유는 작업 통계에 기록합니다.

### 범용 동적 탐색과 누락 점검

URL 입력 시 읽기 전용 탭·접힌 영역·더보기·상세 버튼이 감지되면 브라우저로 전환합니다.
브라우저는 초기 AJAX와 상호작용 응답(동일 호스트 HTML/JSON), 펼쳐진 본문과 새 링크를
수집합니다. 저장·삭제·예약·신청 버튼은 제외하고 POST는 알려진 list/view/detail/pop/
search/query 읽기 경로만 허용합니다. 동적 탐색은 페이지당 100회, AJAX 200응답 및
응답당 1 MiB로 제한합니다. 사이트마다 다른 비표준 UI는 자동으로 완전 수집을 보장하지
않으며 실패·숨은 컨트롤·제한 도달·차단 요청이 있으면 needs_review를 기록합니다.
`GET /api/console/pages/{page_id}/discovery`(관리자 인증)에서 결과를 확인할 수 있습니다.
보고서가 없는 페이지는 checked=false이며 탐색 완료로 간주하지 않습니다.
동일 목록의 page/pageNo/pageIndex/form_page_index/lastKey/offset/cursor 변경은 depth를
증가시키지 않습니다. 카테고리 변경·상세 이동은 증가시키며 max_pages·중복 방지 제한은
유지됩니다. 소마 fnSclptrView 버튼도 별도 상세 URL 후보로 수집합니다.

일반 사이트 크롤링은 기본적으로 모든 HTML 페이지를 브라우저로 렌더링합니다.
`CRAWL_RENDER_ALL_HTML=true`가 기본값이며 소마 이외의 도메인에도 적용됩니다.
`false`로 설정하면 정적 HTML에서 동적 컨트롤 또는 SPA 징후가 발견될 때만 브라우저로 전환합니다.
`CRAWL_DYNAMIC_MAX_ACTIONS=100`은 페이지당 읽기 전용 상호작용의 상한입니다.
한도 도달·브라우저 실패는 discovery_report의 needs_review로 확인해야 합니다.
PDF는 기존대로 첨부 정보만 수집하며, 연결된 외부 사이트의 한 단계 참고 링크 수집은 별도의 HTTP 경로입니다.

사용자 입력 검색: 우편번호·지도·키워드 검색은 검색 화면까지만 수집합니다. 검색/조회 실행과 입력 필드가 있는 검색 폼의 드롭다운·페이지 이동은 자동 탐색하지 않습니다. 입력값을 생성하거나 검색 결과를 요청하지 않습니다. 일반 콘텐츠 탭·펼치기는 계속 탐색합니다.

전체 수집은 해당 사이트의 SONAR 문서·RAG 색인을 먼저 삭제하고 로컬 페이지·종속 데이터를 초기화한 뒤 다시 탐색합니다. 삭제 실패 시 작업은 실패로 종료되며 새 수집을 시작하지 않습니다. 재수집이 끝날 때까지 기존 사이트의 검색 결과는 제공되지 않습니다. 증분 수집은 초기화하지 않고 신규·변경 문서만 반영합니다.


### 전체 수집 탐색 제한과 루프 방지

- 전체 수집은 사이트 설정과 관계없이 최대 2,000개의 고유 URL을 방문 큐에 등록합니다.
  사이트 `max_pages`가 더 작으면 그 설정까지 처리합니다. URL에는 목록·상세·팝업이 포함됩니다.
- 실제 목록 이동 링크를 우선 사용하며, JS 페이지 번호도 명시된 번호만 사용합니다.
- 목록 경로와 필터가 같은 범위에서 상세 링크 집합이 반복되면 해당 목록의 후속 탐색을
  중단합니다. 다른 연도·카테고리와 상세 링크는 유지합니다. 빈 목록·미인식 상세 패턴은
  반복으로 단정하지 않으며 2,000 URL 상한으로 제한합니다.
- 동적 반복 버튼이 이미 관찰한 본문 상태로 돌아오면 그 버튼을 더 이상 반복하지 않습니다.
- 소마 상세 URL의 목록 이동 파라미터는 콘텐츠 정체성에서 제외하되 언어 등 콘텐츠
  구분 값은 보존합니다.
- 작업 상세에 고유 본문 해시 수, 중복 URL 등록 차단 횟수, 대기 URL 수, 반복 목록 차단 수,
  종료 사유를 표시합니다. 중복 횟수는 중복 문서 수가 아닌 등록 시도 횟수입니다.
- URL 상한에 도달해도 종료 상태는 SUCCESS이며 종료 사유 `url_limit`로 범위 제한을
  구분합니다. 배포 전 실행된 작업의 통계는 소급해서 계산하지 않습니다.


### 전체 수집과 게시판 정기 수집

전체 수집은 해당 사이트의 Sonar 콘텐츠·RAG 색인, 수집 DB의 페이지·청크·첨부 및
저장 파일과 해당 사이트의 게시판 소스 등록을 모두 초기화하고 다시 적재합니다.
게시판 소스의 후보·승인·거부·검증 제외 기록과 수동 등록도 삭제됩니다. 다른 사이트의
등록은 유지합니다. 사이트 진입 화면과 사이트맵부터 다시 탐색해 공통 검증을 통과한
최초 목록만 새로 등록하고, 같은 작업에서 최근 90일 게시글을 수집합니다.
게시판 단계와 일반 탐색은 최대 2,000 URL 예산을 공유합니다.

게시판 목록은 자동으로 승인 상태에 등록하며, 기존 후보는 재발견 시 승격합니다.
활성 사이트의 등록된 게시판은 Asia/Seoul 기준 매일 오전 4시에 갱신합니다.
목록에서 최근 90일 글을 확인하고 이미 처리된 URL은 건너뛰므로 신규 글만 적재합니다.
기존 글의 수정·Qdrant에서 직접 지운 색인의 자동 복구는 이 신규 전용 작업의 대상이 아닙니다.

신규 글이 없는 목록에서도 다음 페이지를 탐색합니다. 최신순 목록에서 최근 90일 글이
없는 페이지를 만나면 다음 페이지도 확인하고, 연속 두 페이지가 범위 밖이면 종료합니다.
반복되는 상세 링크 집합·빈 목록·실패·게시판당 200 목록 페이지 제한에서도 종료합니다.
날짜가 있는 고정 공지는 동일한 90일 기준으로 처리하며, 소마 전시·작품은 게시판으로
분류하지 않습니다. 첨부 문서와 본문 이미지는 URL·파일명·추정 MIME 메타데이터만 저장하고
파일 다운로드, 문서 추출, 이미지 OCR·시각 분석은 하지 않습니다.


### 게시판 최초 목록 공통 검증

자동 발견·수동 추가/승인·주간 등록은 동일한 검증 서비스를 사용합니다. 본문의 동일 목록
영역에 서로 다른 게시글 링크가 2개 이상 있고 게시일 열/필드가 확인되어야 등록합니다.
헤더·푸터·추천/관련 글과 동적 수집 합성 영역은 판정에서 제외하며, 전시·행사 기간과
제작연도를 게시일로 사용하지 않습니다. 확실히 식별되지 않는 목록은 자동 등록하지 않고
일반 페이지 수집 대상으로 유지합니다.

등록 URL은 페이지 번호·커서·검색·추적 파라미터를 제거한 최초 목록 주소입니다.
게시판 ID와 카테고리는 보존합니다. 상세 URL에서 목록 주소를 추정한 경우와 후속 목록에서
발견한 경우는 반드시 최초 주소를 다시 읽어 검증합니다. 숫자로 끝나는 상세 경로는
게시판 소스로 등록하지 않으며 다른 호스트의 주소도 거부합니다.

기존 후보/승인 소스는 다음 게시판 작업에서 최초 목록을 재검증합니다. 오등록·최초 주소
중복은 `invalid`(검증 제외)로 분리하고 사유를 저장합니다. 페이지/청크/RAG는 삭제하지 않습니다.
일시적인 HTTP 오류는 검증 제외로 확정하지 않고 다음 작업에서 재시도합니다.
DB 변경은 Alembic revision `0008` (`0007` 이후)으로 `validation_error` 열을 추가합니다.


### 수집과 정제·색인의 병렬 처리

`POSTPROCESS_CONCURRENCY=10` (허용 범위 1~10)으로 Worker 프로세스 전체의 후속 처리 상한을 설정합니다.
일반 전체 수집, 증분, 게시판 갱신, 미수집 보충, URL 단건 수집이 같은 후속 처리 풀을 사용합니다.
브라우저 수집·링크 발견은 기존 순서를 유지하고, 본문을 확보하면 정제·품질 판정·임베딩·로컬 Qdrant 색인을 비동기로 실행합니다.
10건이 모일 때까지 기다리지 않으며, 처리 대기 수가 상한에 도달하면 수집에 역압을 적용합니다.
방문 큐가 비어도 후속 처리가 남아 있으면 RUNNING을 유지하며 전부 정리된 뒤 완료합니다.
서로 다른 사이트 작업도 같은 프로세스의 10개 슬롯을 공유합니다. 동일 도메인의 전체/증분/게시판/단건 작업은 Redis 잠금으로 중첩 초기화를 방지합니다.
Worker 인스턴스를 추가하면 프로세스별 슬롯이 추가되므로 배포 시 전체 동시성을 함께 산정해야 합니다.

화면에는 후속 처리 대기·정제/색인 중·후속 처리 실패를 표시합니다.
실패하거나 중단된 본문은 `storage_paths.processing_pending`을 유지해 다음 증분/게시판/보충 수집에서 재처리합니다.
이 풀은 부모 ARQ 작업에 소속된 비동기 작업으로, 프로세스가 중단되면 해당 작업을 재실행해야 합니다.
별도 DB 스키마 변경은 없으며 기존 원문·정제 파일과 JSONB 필드를 사용합니다.
