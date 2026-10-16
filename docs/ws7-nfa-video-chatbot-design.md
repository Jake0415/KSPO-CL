# WS7: 국민체력100 운동처방 동영상 챗봇 설계

## 개요

국민체력100 사이트(`nfa.kspo.or.kr`)의 운동처방 동영상 699건을 학습하여 질의응답하는 챗봇 파이프라인. 동영상은 YouTube 임베딩이며, 한국어 자동자막(ASR)이 존재. YouTube 자막 API로 전사 텍스트를 추출하고, 사이트의 구조화된 메타데이터(대상, 체력항목, 운동도구, 부위, 질환)와 합성하여 Qdrant에 적재.

## 사이트 분석 결과

- **URL**: `https://nfa.kspo.or.kr/classroom/program/selectPrescriptionMovieList.kspo` (menuId: A03_B05)
- **접근 방식**: `beforeReserve.kspo` 방문 → 세션 쿠키(JSESSIONID) 확보 → `main.kspo` → 동영상 목록 (로그인 불필요)
- **총 동영상**: 699건, 12건/페이지, ~58페이지
- **동영상 소스**: YouTube 임베딩 (`youtube.com/embed/{videoId}`)
- **자막**: 한국어 자동자막(ASR) 존재 (`kind=asr&lang=ko`)
- **동영상 조회**: `fnMovieViewerOpen(movieSn)` → POST `/selectPrescriptionMovieViewJs.kspo` → YouTube embed URL 반환
- **메타데이터 카테고리**:
  - 대상: 유아기, 유소년, 청소년, 성인, 어르신
  - 체력항목: 근력/근지구력, 심폐지구력, 민첩성/순발력, 유연성, 평형성, 협응력
  - 운동부위: 몸통, 상체, 전신, 하체
  - 운동도구: 맨몸, 머신, 의자, 짐볼, 폼롤러, 탄력밴드, 기타
  - 질환: 고혈압, 요통, 골다공증, 관절염, 우울증, 치매, 기타

## 아키텍처

```
nfa.kspo.or.kr (세션 쿠키 확보)
    |
    +-- 동영상 목록 크롤 (699건, 58페이지 페이지네이션)
    |   +-- 각 항목: movieSn, 제목, 대상, 체력항목, 운동도구, 부위
    |
    +-- YouTube ID 추출 (fnMovieViewerOpen -> embed URL)
    |   +-- POST /selectPrescriptionMovieViewJs.kspo -> youtube.com/embed/{videoId}
    |
    +-- YouTube 자막 추출 (timedtext API, kind=asr, lang=ko)
        +-- 자막 텍스트 + 메타데이터 합성
            +-- 청킹 -> 임베딩 -> Qdrant 적재 (tags: 대상, 항목, 도구, 부위, 질환)
```

## 데이터 흐름

| 단계 | 입력 | 출력 | 비용 |
|------|------|------|------|
| 1. 목록 크롤 | 58페이지 POST | 699건 메타 (제목, 대상, 항목, 도구, movieSn) | $0 |
| 2. YouTube ID 추출 | 699건 movieSn | 699건 videoId | $0 |
| 3. 자막 추출 | 699건 videoId | 699건 한국어 전사 텍스트 | $0 |
| 4. 청킹+임베딩 | 메타+자막 합성 텍스트 | Qdrant 포인트 (~2,000~3,000건) | ~$2 |

## 청크 구조 (메타 + 자막 합성)

```
[국민체력100 운동처방 | nfa.kspo.or.kr]
제목: 점핑점핑해요
대상: 유아기 | 체력항목: 심폐지구력 | 운동도구: 목봉/사다리 | 부위: 전신
---
(자막 내용) 오늘은 점핑 운동을 해볼 거예요. 먼저 두 발을 모으고...
```

## Qdrant Payload 구조

```json
{
  "page_content": "(합성 텍스트)",
  "metadata": {
    "id": "nfa-video-{movieSn}-{chunk_index}",
    "source": "https://nfa.kspo.or.kr/classroom/program/selectPrescriptionMovieList.kspo",
    "namespace": "kspo",
    "type": "exercise_video",
    "domain_host": "nfa.kspo.or.kr",
    "title": "점핑점핑해요",
    "youtube_id": "KlDL8qiVZuA",
    "youtube_url": "https://www.youtube.com/watch?v=KlDL8qiVZuA",
    "target_age": "유아기",
    "fitness_item": "심폐지구력",
    "equipment": "목봉/사다리",
    "body_part": "전신",
    "disease": null,
    "tags": ["d:nfa.kspo.or.kr", "t:유아기", "f:심폐지구력", "type:exercise_video", "v:1"]
  }
}
```

## 신규 모듈

| 파일 | 역할 |
|------|------|
| `src/kspo_ingest/crawl/nfa_video.py` | 목록 크롤 (세션 확보, 페이지네이션, 메타 파싱) + YouTube ID 추출 |
| `src/kspo_ingest/crawl/youtube_caption.py` | YouTube 자막 API로 전사 텍스트 추출 |
| `src/kspo_ingest/tasks/pipeline/ingest_videos.py` | 파이프라인 오케스트레이션 (목록 -> 자막 -> 청킹 -> 적재) |
| `tests/test_nfa_video.py` | 목록 크롤 + YouTube ID 추출 테스트 |
| `tests/test_youtube_caption.py` | 자막 추출 테스트 |
| `tests/test_ingest_videos.py` | 파이프라인 통합 테스트 |

## 기존 파이프라인 재사용

| 모듈 | 용도 |
|------|------|
| `chunk/chunker.py` | 자막 텍스트 청킹 (800토큰 기준 동일) |
| `chunk/header.py` | 컨텍스트 헤더 (제목 + 메타데이터) |
| `embed/embedder.py` | text-embedding-3-large 임베딩 |
| `qdrant/adapter.py` | Direct upsert |
| `qdrant/payload.py` | build_payload() 확장 (youtube_id, target_age 등 추가) |
| `api/routers/qa.py` | 동일 QA 엔드포인트로 질의응답 |

## API 엔드포인트

### POST /api/jobs/ingest-videos

동영상 파이프라인 수동 트리거. 관리자 전용.

```json
{
  "max_videos": 699,
  "target_age": null
}
```

## PoC 범위 제안 (공단 협의용)

| 항목 | PoC 범위 | 전체 범위 |
|------|---------|----------|
| 동영상 수 | 50건 (대상별 10건씩) | 699건 전체 |
| 자막 소스 | YouTube 자동자막 | 자동자막 + 수동교정(선택) |
| 필터링 | 대상 + 체력항목 | 전 카테고리 |
| 예상 일정 | 3~5일 | 1~2주 |

## 리스크

| 리스크 | 영향 | 대응 |
|--------|------|------|
| YouTube 자막이 일부 동영상에 없음 | 해당 영상 전사 불가 | 자막 없는 건은 메타데이터만 적재, 로그 기록 |
| 자동자막 품질 낮음 (운동 용어 오인식) | 검색 품질 저하 | PoC 후 품질 평가 → 필요 시 Whisper 전사 전환 |
| 사이트 구조 변경 (menuId, 세션 정책) | 크롤 실패 | 세션 확보 로직 분리, 셀렉터 설정화 |
| YouTube API rate limit | 대량 추출 시 차단 | 요청 간 1초 대기, 배치 처리 |
