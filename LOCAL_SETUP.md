# 독립 로컬 실행

운영 저장소의 커밋된 소스만 복사했습니다. 원본 작업 폴더의 미완료 변경은 포함하지 않았습니다.

- 콘솔: http://localhost:3334
- Qdrant: http://localhost:6334/dashboard
- 로그인 정보: LOCAL_ACCESS.txt (비공개, Git 커밋 금지)
- 실행: `docker compose up -d --build` 또는 `./start-local.ps1`
- 중지: `docker compose stop` 또는 `./stop-local.ps1`
- 상태: `docker compose ps`
- 로그: `docker compose logs --tail 100 worker`

PostgreSQL, Redis, Qdrant, 수집 원본은 kspo-local 전용 Docker 볼륨에 보존됩니다.
스케줄은 비활성화되어 있으며 사용자가 실행한 작업만 처리합니다.
전체 수집은 해당 사이트의 로컬 데이터와 로컬 색인만 초기화합니다.

## 정제와 임베딩

실제 정제 및 벡터 생성에는 `.env`의 `OPENAI_API_KEY`를 설정해야 합니다.
설정 후 `docker compose up -d --force-recreate api worker`로 반영합니다.
모델은 text-embedding-3-large, 벡터 차원은 3072입니다.
운영 Sonar는 연결하지 않았으며 결과는 로컬 Qdrant의 kspo_local 컬렉션에 적재합니다.
`local_worker`는 외부 Sonar 또는 외부 Qdrant 목적지 설정을 거부합니다.

## 로컬 변경

compose.yaml, nginx.local.conf, local_worker.py를 추가했습니다.
push_to_sonar의 로컬 모드는 기존 chunk_and_index를 호출하며,
전체 수집의 초기화도 로컬 Qdrant에 적용합니다.
원본 D:/project/Sonar는 변경하지 않았습니다.

소스와 configs는 읽기 전용 바인드 마운트입니다. Python 소스 수정 후에는 `docker compose restart api worker`로 반영합니다. 의존성 변경은 다시 빌드해야 합니다.


## 2026-10-16 로컬 수집 속도 개선

- 시작 검증은 리다이렉트와 본문 준비만 확인하며 동적 버튼 탐색을 하지 않습니다.
- 실제 수집은 기존 최대 100회 동적 탐색을 유지합니다.
- 동일한 명시적 nav/header 메뉴는 구조와 URL 기준이 같은 경우 발견 링크를 재사용합니다.
- 본문 탭, 더보기, 드롭다운, 본문이 바뀌는 메뉴는 캐시하지 않습니다.
- 캐시는 메모리에만 저장하며 새 작업의 시작 검증 시 초기화됩니다.
- HTTP 오류 페이지는 동적 메뉴 탐색을 생략합니다.
- 긴 탐색 중 브라우저 응답이 해제되지 않도록 응답 헤더를 먼저 보관합니다.

## 로그인 세션

`SESSION_MAX_AGE_SECONDS=0`으로 자동 로그인 만료를 비활성화합니다.
로그아웃은 정상 동작하며, 브라우저의 세션 쿠키 삭제 또는 세션 종료 시 재로그인이 필요할 수 있습니다.
수집 작업·네트워크 요청의 제한 시간과는 별개입니다.

## 수집 오류와 재시도 개선

- 첫 화면을 다시 로드하지 않고 초기 AJAX 응답을 관측합니다. 동적 탐색 중 화면 이동이 실패해도 이미 확보한 본문은 보존합니다.
- 게시판 JS에 명시된 상세 경로와 ID 필드를 우선 사용합니다. 알 수 없는 `.do`·`.kspo` 목록에 `/글번호`를 임의로 붙이지 않습니다.
- 다운로드 핸들러와 PDF 등 바이너리는 본문 크롤링 대상에서 제외하고 부모 페이지에 첨부 메타데이터로 보관합니다.
- 빈 meta/onclick 속성과 원문 인코딩을 안전하게 처리합니다.
- 정제 호출은 SDK 중복 재시도를 끄고 `REFINE_MAX_ATTEMPTS=2`, 요청당 60초, 전체 125초를 기본으로 사용합니다.
- 기존 실패 작업을 자동으로 재실행하거나 기존 색인을 초기화하지 않습니다.
