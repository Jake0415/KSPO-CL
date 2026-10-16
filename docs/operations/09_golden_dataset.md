# Golden Dataset — KSPO RAG Regression Test

> **Purpose:** 모든 코드/설정 변경 후 검색 품질과 RAG 응답 품질이 저하되지 않는지 검증
> **Size:** 100 대표 문서 (크롤 후 채움) + 50 평가 질문

---

## 구조

```
golden_dataset/
├── documents/            # 100개 대표 문서
│   ├── doc_001.json
│   ├── doc_002.json
│   └── ...
├── queries/              # 50개 평가 질문
│   ├── queries.json
│   └── expected_results.json
├── baselines/            # 기준 점수 (최초 측정값)
│   └── baseline_YYYY-MM-DD.json
└── results/              # 실행 결과 (매 변경 시)
    └── result_YYYY-MM-DD.json
```

---

## Document Schema (각 문서)

```json
{
  "doc_id": "doc_001",
  "url": "https://www.kspo.or.kr/front/board/boardList.do?...",
  "domain_host": "www.kspo.or.kr",
  "category": "notice",
  "title": "2026년 하반기 수영장 운영시간 안내",
  "raw_html_sha256": "abc123...",
  "extracted_body": "올림픽수영장 운영시간을 다음과 같이...",
  "summary": "2026년 7월부터 올림픽수영장 운영시간이 변경...",
  "keywords": ["수영장", "운영시간", "올림픽공원"],
  "quality_score": 0.85,
  "structure_score": 0.92,
  "quadrant": "Q1",
  "posted_at": "2026-06-15T00:00:00+09:00",
  "expected_collections": ["tilellm", "kspo_knowledge"],
  "search_keywords": ["올림픽수영장 시간", "수영장 운영"],
  "expected_search_rank": 1,
  "expected_qa_answer": "올림픽수영장은 07:00~21:00에 운영됩니다.",
  "expected_citation_url": "https://www.kspo.or.kr/front/board/..."
}
```

---

## 카테고리별 문서 분배 (100개)

| 카테고리 | 수량 | 대표 사이트 | 설명 |
|----------|------|-------------|------|
| 공지사항 | 20 | kspo.or.kr | 일반 공지, 채용, 입찰 |
| 시설 안내 | 15 | kspo.or.kr, spoex.com | 시설 소개, 운영정보 |
| 예약/요금 | 10 | kspo.or.kr | 이용료, 예약 방법 |
| 기관 소개 | 10 | kspo.or.kr | 비전, 조직, 사업 |
| 국민체력100 | 10 | nfa.kspo.or.kr | 체력측정, 운동처방 |
| 이벤트/프로그램 | 10 | kspo.or.kr | 문화행사, 체육교실 |
| 패밀리사이트 | 15 | 각 패밀리 | 자전거, 조정, 호텔 |
| FAQ/정책 | 10 | kspo.or.kr | 이용수칙, 환불정책 |
| **합계** | **100** | | |

---

## 회귀 테스트 절차

### 1. 문서 수집 (최초 1회)

```bash
# Full Crawl 완료 후 실행
python scripts/build_golden_dataset.py \
  --output golden_dataset/documents/ \
  --count 100 \
  --categories notice,facility,reservation,about,nfa,event,family,faq
```

### 2. 기준선 측정 (최초 1회)

```bash
python scripts/run_golden_eval.py \
  --dataset golden_dataset/ \
  --output golden_dataset/baselines/baseline_$(date +%F).json
```

### 3. 변경 후 회귀 테스트

```bash
# 코드 변경 후
python scripts/run_golden_eval.py \
  --dataset golden_dataset/ \
  --baseline golden_dataset/baselines/baseline_2026-07-05.json \
  --output golden_dataset/results/result_$(date +%F).json
```

### 4. 판정

| 메트릭 | 허용 범위 | FAIL 조건 |
|--------|-----------|-----------|
| 검색 Recall@5 | baseline ± 5% | 5% 이상 하락 |
| 검색 MRR@5 | baseline ± 0.05 | 0.05 이상 하락 |
| RAG Groundedness 평균 | baseline ± 0.3 | 0.3 이상 하락 |
| RAG Hallucination율 | baseline + 5% | 5% 이상 증가 |
| Collection Routing 정확도 | 100% | 1건이라도 잘못된 라우팅 |

---

## 질문 카테고리별 기대 응답 형식

### 사실 확인형 (Factual)

```json
{
  "query_id": "F_001",
  "question": "올림픽수영장 운영시간은?",
  "type": "factual",
  "expected_answer_contains": ["07:00", "21:00"],
  "expected_source_domain": "www.kspo.or.kr",
  "grounding_required": true
}
```

### 목록형 (List)

```json
{
  "query_id": "L_001",
  "question": "KSPO가 운영하는 경기장은?",
  "type": "list",
  "expected_answer_contains": ["체조경기장", "수영장", "핸드볼"],
  "min_items": 3,
  "grounding_required": true
}
```

### 비교형 (Comparison)

```json
{
  "query_id": "C_001",
  "question": "올림픽수영장과 일반 수영장의 차이는?",
  "type": "comparison",
  "expected_aspects": ["규격", "수심", "레인"],
  "grounding_required": true
}
```

### 불가능형 (Unanswerable)

```json
{
  "query_id": "U_001",
  "question": "내일 날씨가 어떤가요?",
  "type": "unanswerable",
  "expected_answer_contains": ["답변할 수 없", "관련 정보가 없"],
  "should_not_hallucinate": true
}
```

---

## 자동화 스크립트 요구사항

### `scripts/build_golden_dataset.py`

- DB에서 INDEXED 상태 페이지 중 Q1/Q2 문서 선정
- 카테고리별 균등 분배
- raw HTML + 추출 본문 + 품질 점수 + Qdrant 존재 여부 기록
- JSON Lines 형식으로 저장

### `scripts/run_golden_eval.py`

- 각 문서의 검색 키워드로 Qdrant 검색
- Recall@5, MRR@5 계산
- 50개 질문 → /api/qa 호출 → 응답 수집
- baseline과 비교 → PASS/FAIL 판정
- JSON 리포트 생성

---

## 유지보수

| 주기 | 작업 |
|------|------|
| 코드 변경 시 | `run_golden_eval.py` 실행, FAIL 시 머지 차단 |
| 분기 1회 | 질문 10개 추가/갱신 (사이트 콘텐츠 변경 반영) |
| 반기 1회 | Golden Dataset 전체 재수집 (문서 100개 교체) |
| 모델 변경 시 | Baseline 재측정 (새 모델의 기준값) |
