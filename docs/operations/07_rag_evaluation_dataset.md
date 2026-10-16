# RAG Evaluation Dataset

> **Version:** 1.0
> **Purpose:** QA API 품질 평가를 위한 50개 질문 + Golden Answer + 평가 기준
> **Domain:** KSPO (국민체육진흥공단) 웹사이트

---

## 평가 기준

각 질문에 대해 다음을 평가한다:

| 항목 | 설명 | 점수 |
|------|------|------|
| **Groundedness** | 답변이 제공된 소스에 기반하는가 | 0~5 |
| **Faithfulness** | 답변이 소스의 내용을 왜곡하지 않는가 | 0~5 |
| **Relevance** | 답변이 질문에 적절한가 | 0~5 |
| **Citation Accuracy** | Citation이 실제 출처를 정확히 가리키는가 | 0~5 |
| **Hallucination** | 소스에 없는 정보를 만들어냈는가 | Yes/No |

**합격 기준:**
- 평균 Groundedness >= 3.5
- 평균 Faithfulness >= 4.0
- Hallucination율 <= 10% (50개 중 5개 이하)
- Citation Accuracy >= 80% (citation 있는 답변 중 정확한 비율)

---

## 카테고리별 질문 (50개)

### A. 기관 소개 (5문항)

| # | Question | Expected Topic | Expected Source |
|---|----------|---------------|-----------------|
| A1 | 국민체육진흥공단은 어떤 기관인가요? | 기관 소개, 설립 목적 | kspo.or.kr/about |
| A2 | KSPO의 주요 사업은 무엇인가요? | 체육진흥, 시설운영, 기금 | kspo.or.kr/business |
| A3 | 국민체육진흥공단의 조직 구조를 알려주세요 | 이사장, 본부, 팀 | kspo.or.kr/organization |
| A4 | 공단의 미션과 비전은 무엇인가요? | 미션/비전 선언문 | kspo.or.kr/vision |
| A5 | 국민체육진흥공단의 위치는 어디인가요? | 서울 송파구 올림픽로 | kspo.or.kr/contact |

### B. 시설 안내 (10문항)

| # | Question | Expected Topic | Expected Source |
|---|----------|---------------|-----------------|
| B1 | 올림픽공원에는 어떤 시설이 있나요? | 체조경기장, 수영장 등 | kspo.or.kr/facilities |
| B2 | 올림픽수영장 이용 시간은? | 운영시간 06:00~21:00 등 | 시설 상세 페이지 |
| B3 | 올림픽공원 체조경기장 좌석 수는? | 좌석 수 정보 | 시설 상세 페이지 |
| B4 | 올림픽공원 주차장 요금은? | 주차비 안내 | 주차 안내 페이지 |
| B5 | 벨로드롬은 어디에 있나요? | 위치 정보 | kcycle.or.kr |
| B6 | 미사리조정경기장 이용 방법은? | 예약/이용 절차 | kboat.or.kr |
| B7 | 올림픽공원 잔디광장 대관 방법은? | 대관 절차 | kspo.or.kr/rental |
| B8 | KSPO DOME에서 열리는 행사는? | 공연/이벤트 | kspo.or.kr/dome |
| B9 | 올림픽공원 산책로가 있나요? | 산책 코스 | kspo.or.kr/park |
| B10 | 핸드볼경기장 수용 인원은? | 좌석 수 | 시설 상세 |

### C. 예약 (8문항)

| # | Question | Expected Topic | Expected Source |
|---|----------|---------------|-----------------|
| C1 | 올림픽수영장 예약은 어떻게 하나요? | 온라인 예약 절차 | 예약 안내 페이지 |
| C2 | 체육시설 이용료는 얼마인가요? | 요금표 | 요금 안내 |
| C3 | 수영장 회원권이 있나요? | 회원제 안내 | 회원 안내 |
| C4 | 시설 예약 취소 정책은? | 환불/취소 규정 | 이용약관 |
| C5 | 단체 예약은 몇 명부터 가능한가요? | 단체 기준 | 단체 안내 |
| C6 | 주말에도 시설 이용이 가능한가요? | 주말 운영시간 | 운영시간 안내 |
| C7 | 할인 혜택이 있나요? (장애인, 경로) | 할인 정책 | 요금 안내 |
| C8 | 올림픽공원 야외 시설 예약 방법은? | 야외 시설 예약 | 예약 안내 |

### D. 운영 정보 (7문항)

| # | Question | Expected Topic | Expected Source |
|---|----------|---------------|-----------------|
| D1 | 올림픽공원 운영시간은? | 공원 개방 시간 | 이용안내 |
| D2 | 공휴일에도 운영하나요? | 휴관일 안내 | 이용안내 |
| D3 | 올림픽공원 교통편은? | 지하철, 버스 | 오시는길 |
| D4 | 반려동물 입장이 가능한가요? | 반려동물 정책 | 이용수칙 |
| D5 | 올림픽공원 내 편의시설은? | 편의점, 카페, 화장실 | 편의시설 안내 |
| D6 | 음식물 반입이 가능한가요? | 반입 규정 | 이용수칙 |
| D7 | 올림픽공원 와이파이 사용 가능한가요? | WiFi 안내 | 편의시설 |

### E. 공고/채용 (5문항)

| # | Question | Expected Topic | Expected Source |
|---|----------|---------------|-----------------|
| E1 | 국민체육진흥공단 채용 공고가 있나요? | 최신 채용 정보 | 채용 공고 |
| E2 | 입사 지원 방법은? | 지원 절차 | 채용 안내 |
| E3 | 인턴 프로그램이 있나요? | 인턴 채용 | 채용 공고 |
| E4 | 최근 입찰/조달 공고는? | 입찰 공고 | 조달 공고 |
| E5 | 공단 복리후생은 어떤가요? | 복지 정보 | 채용 안내 |

### F. 이벤트/프로그램 (5문항)

| # | Question | Expected Topic | Expected Source |
|---|----------|---------------|-----------------|
| F1 | 현재 진행 중인 이벤트가 있나요? | 최신 이벤트 | 이벤트 게시판 |
| F2 | 체육교실 프로그램이 있나요? | 체육 강좌 | 프로그램 안내 |
| F3 | 어린이 체험 프로그램은? | 어린이 프로그램 | 체험 안내 |
| F4 | 올림픽기념관 전시 일정은? | 전시 정보 | 기념관 안내 |
| F5 | 올림픽공원 문화행사 일정은? | 공연/축제 | 문화행사 안내 |

### G. 국민체력100 (5문항)

| # | Question | Expected Topic | Expected Source |
|---|----------|---------------|-----------------|
| G1 | 국민체력100이란 무엇인가요? | 체력 측정 사업 | nfa.kspo.or.kr |
| G2 | 체력 측정은 어디서 받을 수 있나요? | 측정 센터 위치 | nfa.kspo.or.kr/center |
| G3 | 체력 측정 비용은? | 무료/유료 안내 | nfa.kspo.or.kr |
| G4 | 운동처방을 받으려면? | 운동처방 절차 | nfa.kspo.or.kr/prescription |
| G5 | 체력 인증서 발급 방법은? | 인증서 안내 | nfa.kspo.or.kr/cert |

### H. 비교/요약/복합 (5문항)

| # | Question | Expected Topic | Expected Source |
|---|----------|---------------|-----------------|
| H1 | 올림픽수영장과 일반 수영장의 차이점은? | 규격, 시설 비교 | 시설 상세 |
| H2 | KSPO 패밀리 사이트는 몇 개인가요? | 17개 패밀리 | kspo.or.kr |
| H3 | 올림픽공원의 역사를 요약해주세요 | 88올림픽 유산 | 공원 소개 |
| H4 | 스포렉스 시설은 어떤 것들이 있나요? | spoex.com 시설 | spoex.com |
| H5 | 공단이 운영하는 경기장 목록은? | 시설 전체 목록 | kspo.or.kr/facilities |

---

## 평가 수행 방법

### 1. 자동 수집

```bash
# 50개 질문 일괄 실행
for q in "${QUESTIONS[@]}"; do
  curl -s -X POST http://localhost/api/qa \
    -H "Content-Type: application/json" \
    -d "{\"question\": \"$q\"}" >> results.jsonl
done
```

### 2. 사람 평가 (각 응답에 대해)

각 응답에 대해 평가자가 기입:

```json
{
  "question_id": "A1",
  "groundedness": 4,
  "faithfulness": 5,
  "relevance": 5,
  "citation_accuracy": 4,
  "hallucination": false,
  "notes": "답변이 정확하나 설립 연도 미포함"
}
```

### 3. 집계

```
평균 Groundedness: X.X / 5.0
평균 Faithfulness: X.X / 5.0
평균 Relevance: X.X / 5.0
Citation Accuracy: XX%
Hallucination Rate: X/50 (X%)
```

### 4. 판정

- 모든 평균 >= 3.5 AND Hallucination <= 10% → **RAG PASS**
- 그 외 → **RAG FAIL** (재크롤 또는 프롬프트 튜닝 필요)

---

## Golden Dataset 관리

이 데이터셋은 회귀 테스트용으로 영구 관리한다:

1. **버전 관리:** `docs/operations/07_rag_evaluation_dataset.md` (이 파일)
2. **결과 저장:** `docs/reports/rag_eval_YYYY-MM-DD.json`
3. **회귀 기준:** 이전 평가 대비 평균 점수 0.5 이상 하락 시 배포 중단
4. **업데이트:** 분기 1회 질문 추가/수정 (사이트 콘텐츠 변경 반영)
