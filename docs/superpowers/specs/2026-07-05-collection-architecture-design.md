# Collection Architecture Design — Data Maturity Layers

## 배경

KSPO 크롤링 파이프라인의 데이터를 품질·성숙도에 따라 계층적으로 관리하고,
최종 고품질 데이터만 Tiledesk 챗봇용 `tilellm` 컬렉션에 publish하는 아키텍처.

## 제약

- Tiledesk는 RFP 요건. `tilellm` 컬렉션은 유지.
- 기존 PostgreSQL 7 테이블 + Qdrant `tilellm` 구조 유지하면서 점진 적용.
- 기존 테스트 519개 통과 유지.

---

## 1. Data Maturity Layers

```
Layer 0: RAW          — 수집 원본 (HTML, 첨부 바이너리)
Layer 1: EXTRACTED    — 본문 추출 + 메타데이터 파싱
Layer 2: ENRICHED     — LLM 정제 + 요약 + 키워드 + 품질평가
Layer 3: KNOWLEDGE    — 청킹 + 임베딩 + 관계 매핑
Layer 4: PUBLISHED    — tilellm에 publish된 고품질 데이터
Layer 5: ARCHIVE      — 만료/저품질 데이터 격리
```

### 저장소 매핑

| Layer | PostgreSQL | Qdrant | File Storage |
|-------|-----------|--------|-------------|
| RAW | pages (FETCHED) | - | /data/raw/ |
| EXTRACTED | pages (CLEANED) | - | /data/extracted/ |
| ENRICHED | pages (REFINED) + doc_quality | - | /data/enriched/ |
| KNOWLEDGE | chunks + doc_relations | kspo_knowledge | /data/chunks/ |
| PUBLISHED | chunks (kb_status=OK) | tilellm | - |
| ARCHIVE | pages (ARCHIVED) | kspo_archive | 유지 |

---

## 2. Quadrant 모델

| Quadrant | 조건 | 액션 |
|----------|------|------|
| Q1 PUBLISH | quality >= 0.6, structure >= 0.6 | tilellm publish |
| Q2 ENRICH | quality >= 0.6, structure < 0.6 | LLM 재정제 후 Q1 승격 |
| Q3 RE-CRAWL | quality < 0.6, structure >= 0.4 | 재크롤 예약 |
| Q4 ARCHIVE | quality < 0.6, structure < 0.4 | archive 이동 |

### 점수 산정

```
quality_score = avg(text_length_score, extraction_confidence,
                    korean_ratio, freshness_score, duplicate_score)

structure_score = avg(has_title, has_posted_at, has_summary,
                      keyword_count/15, metadata_completeness)
```

---

## 3. 신규 테이블: doc_quality

```sql
CREATE TABLE doc_quality (
    page_id       BIGINT PRIMARY KEY REFERENCES pages(id) ON DELETE CASCADE,
    quality_score    NUMERIC(4,3) NOT NULL DEFAULT 0,
    structure_score  NUMERIC(4,3) NOT NULL DEFAULT 0,
    freshness_score  NUMERIC(4,3) NOT NULL DEFAULT 0,
    trust_score      NUMERIC(4,3) NOT NULL DEFAULT 1.0,
    importance_score NUMERIC(4,3) NOT NULL DEFAULT 0,
    duplicate_score  NUMERIC(4,3) NOT NULL DEFAULT 1.0,
    quadrant         TEXT NOT NULL DEFAULT 'Q2',
    extraction_method TEXT,
    body_length      INTEGER DEFAULT 0,
    korean_ratio     NUMERIC(4,3) DEFAULT 0,
    has_title        BOOLEAN DEFAULT FALSE,
    has_posted_at    BOOLEAN DEFAULT FALSE,
    has_summary      BOOLEAN DEFAULT FALSE,
    keyword_count    INTEGER DEFAULT 0,
    scorer_version   INTEGER DEFAULT 1,
    scored_at        TIMESTAMPTZ DEFAULT now(),
    published_at     TIMESTAMPTZ,
    archived_at      TIMESTAMPTZ
);
```

---

## 4. Document Lifecycle

```
DISCOVERED → FETCHED → EXTRACTED → ENRICHED → SCORED
                                                  │
                                    Q1 → INDEXED → PUBLISHED
                                    Q2 → re-enrich → Q1
                                    Q3 → RE-CRAWL queue
                                    Q4 → ARCHIVED
```

## 5. Publish 규칙

tilellm에 upsert되려면:
- quadrant == Q1
- quality_score >= 0.6
- freshness_score >= 0.3
- duplicate_score >= 0.5

## 6. Qdrant Payload 확장

기존 metadata에 추가:
- quality_score, quadrant, freshness_score, trust_score
- doc_type (notice, policy, faq, general)

## 7. 마이그레이션 (6단계)

1. doc_quality 테이블 + 스코어링 모듈 (기존 무변경)
2. refine 후 자동 scoring + quadrant 배정
3. publish 게이트 (Q1만 tilellm upsert)
4. kspo_knowledge 컬렉션 (내부 전체 임베딩)
5. Archive cron (freshness 만료 자동 이동)
6. Parent-Child chunking
