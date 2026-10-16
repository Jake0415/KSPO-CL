# Landing-hub 적재 제외 + 코퍼스 중복(scheme 쌍둥이) 정리 — 설계

- 날짜: 2026-07-26
- 대상 코드베이스: `kspo-ingest`
- 발단: `https://www.kspo.or.kr/news/main/main.do`가 (1) 내용 없는 랜딩 허브임에도 품질 게이트를 통과해 INDEXED 되었고, (2) http/https·구버전 해시로 **3중 중복 적재**됨을 확인.

## 배경 / 근거

- `/news/main/main.do`는 시드가 아니라 홈페이지(`/kspo/main/main.do`) BFS가 발견한 뉴스포털 랜딩(depth 1~2).
- KSPO는 eGov 포털 구조라 서브시스템마다 `/{subsystem}/main/main.do` 인덱스 페이지가 존재(`/kspo/`, `/news/`, `/front/`, `/global/` …). 이들은 JS 렌더 내비/대시보드 허브로 고유 텍스트가 거의 없음.
- `url_class.is_non_content_url()`에는 `main.do`를 거르는 규칙이 없어 frontier를 통과 → 적재됨.
- 저장된 `url_hash`가 구버전(scheme 포함)·신버전(scheme 제외, 커밋 `f9bb346`)이 섞여 동일 페이지가 서로 다른 hash로 갈라져 중복 적재. 실측: `news/main/main.do` 3 row, 3개 hash 전부 상이.

## 설계 원칙 (핵심 함정)

랜딩 허브는 **내용은 없지만 링크가 풍부한 BFS 진입점**이다. frontier 분류기(`url_class`)에서 막으면 fetch가 안 되고 그 아래 링크 발견이 끊긴다. 따라서 **crawl·link 발견은 유지하고 "적재(chunk/embed/Qdrant publish)"만 차단**한다.

---

## ① main.do 랜딩 허브 적재 제외

### 1-a. 허브 판별 함수 (신규)

`src/kspo_ingest/crawl/url_class.py`에 추가:

```python
def is_landing_hub(url_or_path: str) -> bool:
    """정규화 path가 '/main/main.do'로 끝나면 eGov 서브시스템 랜딩 허브로 판정.
    내용 없는 내비 허브 — 적재(publish) 대상에서 제외하되 crawl/link 발견은 유지."""
```

- 규칙: 정규화된 path(소문자)가 **`/main/main.do`로 끝남**. `/kspo/main/main.do`, `/news/main/main.do`, `/front/main/main.do`, `/global/main/main.do` 등 서브시스템 인덱스만 매칭. 콘텐츠 `*.do`(예: `view.do`, `list.do`, `contents.do`)는 매칭 안 됨 → 오검출 위험 낮음.
- 위치 근거: `url_class`는 이미 "모든 크롤러 공유 URL 규칙의 단일 홈".
- `is_non_content_url()`과 **분리** 유지 — 후자는 frontier 차단용, 전자는 publish 차단용. 의미가 다르므로 함수도 분리.

### 1-b. 적재 차단 (단일 chokepoint)

`src/kspo_ingest/quality/embedding_policy.py`:

```python
def resolve_embedding_targets(score, policy=None, *, url: str | None = None) -> list[str]:
    if url and is_landing_hub(url):
        return []          # 랜딩 허브: doc_quality 기록만, publish 스킵
    ...
```

- 세 진입 태스크(`enqueue_seeds`, `run_incremental`, `refresh_url`)가 모두 `resolve_embedding_targets(score)`를 거치므로 여기가 단일 chokepoint. 각 호출부에서 page URL을 `url=`로 전달.
- 반환 `[]` → 기존 "targets 비면 chunk_and_index 스킵" 경로를 그대로 탐. `doc_quality`에는 실제 quadrant가 기록됨(기존 "Q2~Q4 기록만" 패턴과 동일).

### 1-c. 기존 적재 허브 1회성 정리 (backfill)

- ②의 dedup은 중복만 없애고 canonical 허브 1건은 INDEXED로 남김. 따라서 이미 적재된 랜딩 허브를 별도로 정리해야 함.
- 방법: cron `archive_expired_documents`와 동일 패턴 — 대상 page의 `chunks.qdrant_point_id`를 active 컬렉션(`tilellm`, `kspo_knowledge`)에서 삭제 → `chunks` 삭제(CASCADE 활용 가능) → `pages.status='DROPPED'` 전환.
- 구현 위치: ②의 정리 스크립트에 `--purge-hubs` 스텝으로 합치거나 별도 함수. dry-run 지원.

### 1-d. 테스트

- `is_landing_hub`: 허브 O(`/news/main/main.do`, 대문자/쿼리 포함), 콘텐츠 X(`/news/bbs/.../view.do`, `/contents.do`).
- `resolve_embedding_targets(score=Q1, url=hub)` → `[]`; `url=콘텐츠` → 기존 매핑 유지; `url=None` → 기존 동작(하위호환).

---

## ② 코퍼스 전체 중복(scheme 쌍둥이) 정리 스크립트

### 2-a. 중복 판정 — 현행 로직으로 재계산

저장된 `url_hash`는 구/신버전이 섞여 신뢰 불가. 모든 page에 대해 **현행 `normalize_url(url)`로 canonical url_hash를 재계산**하고 그 값으로 그룹핑. scheme 쌍둥이(주 대상)뿐 아니라 구버전 해시로 갈라진 중복까지 현재 정체성 기준으로 수렴.

### 2-b. 그룹 내 canonical 선정 (순수함수)

우선순위: **① scheme=`https` → ② 최저 `depth` → ③ status=INDEXED 우선 → ④ tie면 최소 `id`.**

### 2-c. 비-canonical row 제거

FK가 전부 `ON DELETE CASCADE`임을 확인 (`chunks`, `attachments`, `llm_usage`, `doc_quality` → `pages`). 따라서 page 삭제 시 파생 데이터는 자동 삭제되나, 아래 순서를 지켜야 함:

1. **Qdrant 포인트 먼저 삭제**: page 삭제 전에 `chunks.qdrant_point_id`를 수집해 active 컬렉션(`tilellm`, `kspo_knowledge`)에서 삭제. (page를 먼저 지우면 chunks가 CASCADE로 사라져 point_id 참조를 잃음.)
2. **`llm_usage.page_id` → canonical로 재지정**: llm_usage는 비용/예산 감사 이력이라 CASCADE 삭제 시 과거 비용이 과소집계됨. canonical로 옮겨 보존.
3. `pages` row 삭제 → `chunks`/`attachments`/`doc_quality`는 CASCADE로 정리. (canonical이 자체 동등 데이터 보유하므로 중복분 손실 무해.)

### 2-d. 안전장치

- 위치: `scripts/dedup_scheme_twins.py` (기존 `scripts/qdrant_migrate.py`와 동일 위치·스타일).
- **`--dry-run`이 기본**: 중복 그룹 수 / 삭제 예정 page 수 / 재지정 예정 llm_usage 수 / 삭제 예정 Qdrant 포인트 수만 리포트. 아무것도 삭제 안 함.
- `--execute`로만 실제 수행. 그룹 단위 트랜잭션. Qdrant 삭제 실패는 로그만 남기고 진행(운영 KB 정합성 우선, cron 패턴과 동일).

### 2-e. 테스트

- canonical 선정 순수함수 단위테스트: (https/http) × (depth) × (status) 조합.
- 중복 그룹핑: 동일 논리 URL의 http/https/구버전-hash가 한 그룹으로 수렴하는지.
- dry-run을 실 DB에 실행해 건수 sanity check(삭제 없음).

---

## 범위 밖 (YAGNI)

- `url_class.is_non_content_url()` 규칙 확장(랜딩 허브를 frontier에서 막는 것)은 **하지 않음** — 링크 발견 손상.
- 게시판 board_source confirm, incremental 주간 cron 추가 등은 별도 작업.
- 정규화 로직(`_identity_hash`) 자체 변경 없음 — 이미 scheme 제외로 수정됨. 본 작업은 그 규칙에 코퍼스를 **소급 정합**시키는 것.

## 성공 기준

1. `is_landing_hub` + `resolve_embedding_targets` 단위테스트 통과.
2. dedup canonical 선정 단위테스트 통과.
3. dry-run이 `news/main/main.do` 3 row를 1 그룹·삭제예정 2건으로 보고.
4. `--execute` 후: `news/main/main.do` canonical 1 row만 남고 status=DROPPED(허브 정리), 코퍼스 scheme 쌍둥이 그룹 0.
