# 수동 크롤 트리거 (도메인 입력) — 설계

> 2026-07-18. 대시보드에서 도메인을 직접 입력해 크롤을 수동 실행하는 기능.

## 배경
백엔드 API(`POST /api/jobs/full/{domain_id}`)와 프론트 훅(`useTriggerFullJob`)은
이미 존재하나, 이를 호출하는 UI가 없어 운영자가 크롤을 수동 실행할 수 없다.
(지금까지 터미널로 직접 트리거해 옴.)

## 요구사항
- 대시보드에서 **도메인 주소를 직접 타이핑**해 크롤 시작
- 입력이 **미등록 도메인이면 자동 등록 후 크롤** (기본 설정값 사용)
- 전체(full) / 증분(incremental) 선택

## 백엔드 — 엔드포인트 1개
`POST /api/jobs/crawl`
- body: `{ input: str, job_type: "full" | "incremental" }`
- 흐름:
  1. `_extract_host(input)` — scheme/path/공백 제거, 소문자화. 빈 값이면 422.
  2. host로 `Domain` 조회. 없으면 `Domain(host=..., scheme="https", display_name=host)`
     기본값으로 생성 (created=True). 비활성 도메인이면 재활성화.
  3. 기존 `_trigger_job(s, domain_id, job_type, arq_function)` 재사용.
     `arq_function` = full→`enqueue_seeds`, incremental→`run_incremental`.
  4. 반환: `{ job: JobOut, domain_host: str, created: bool }`
- 순수 헬퍼 `_extract_host()`는 단위 테스트 대상.

## 프론트엔드
- `web/api/jobs.ts`: `useTriggerCrawlByHost()` 뮤테이션 + 반환 타입.
- `/jobs` 페이지 상단에 "새 크롤" 카드:
  - 텍스트 입력(도메인/URL), 전체·증분 토글(기본 전체), "크롤 시작" 버튼
  - 성공 토스트: "크롤 시작됨" (+ created면 "도메인 자동 등록됨")
  - 목록은 기존 5초 폴링으로 자동 갱신

## 테스트
- `_extract_host` 단위 테스트: `https://www.x.kr/a?b=1`→`www.x.kr`, `WWW.X.KR`→`www.x.kr`,
  `x.kr`→`x.kr`, 빈/공백→에러.
- 엔드포인트 테스트: 기존 도메인 재사용 경로 / 신규 자동등록 경로(created=True).

## 범위 밖
- 실시간 진행률 스트리밍, 도메인 세부설정 입력(자동등록은 기본값), 크롤 취소(기존 기능).
