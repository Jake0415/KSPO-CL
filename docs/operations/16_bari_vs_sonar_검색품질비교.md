# 검색 품질 비교 리포트 — bari-chatbot vs Sonar

> 2026-07-19. KSPO 챗봇(Sonar)이 "찾을 수 없다"를 자주 내는 원인 진단 겸,
> bari-chatbot의 검색 아키텍처와 정면 비교.

## 결론 한 줄
**bari는 "제대로 만든 하이브리드 RAG", Sonar(현 운영설정)는 "가장 약한 순수 dense".**
Sonar는 좋은 기능을 다 갖췄지만 **운영에서 전부 꺼둔 상태**라 KSPO 질문에 약하다.

---

## 1. 핵심 비교표

| 항목 | **bari-chatbot** | **Sonar (현 운영)** | 승 |
|---|---|---|---|
| 검색 방식 | **Hybrid** (Dense+BM25+RRF) | 순수 Dense | 🟢 bari |
| Dense 임베딩 | text-embedding-3-large (1024d) | ada-002 (1536d) | 🟢 bari (신형 모델) |
| Sparse/키워드 | **Elasticsearch BM25 + 한국어 Nori 형태소** | 미사용 (SPLADE 있으나 OFF) | 🟢 bari |
| Fusion | **RRF (k=60)** | 없음 | 🟢 bari |
| Reranking | **Cross-Encoder bge-reranker-v2-m3** | 미사용 (있으나 OFF) | 🟢 bari |
| Query Rewriting | **LLM 재작성** (구어체→검색어) | contextualize 있으나 기본 OFF | 🟢 bari |
| top_k | 20→10→**5** (단계적) | **4** (위젯 기본) | 🟢 bari |
| Chunk | 문장분할 300/50 | 1000/400 | ~ |
| 답변 grounding | "모르면 모른다" + "관련되면 안내" | "충분치 않으면 `<NOANS>`" | 🟢 bari (덜 보수적) |
| 평가 체계 | **nDCG/MRR/Recall/MAP + 4단계 벤치** | 없음 | 🟢 bari |

---

## 2. bari의 검색 파이프라인 (강점)

```
질문 → [LLM 쿼리 재작성] → 임베딩
   ├─ Dense (Qdrant, top20)
   └─ BM25 (ES + 한국어 Nori, top20)
        ↓ RRF 융합 (k=60)
      상위 10 → [Cross-Encoder 재순위] → 상위 5 → LLM 답변(+출처)
```
- **키워드 검색(BM25)** 이 있어 "체력측정 비용" 같은 정확어 질문에 강함
- **Query Rewriting** 이 "비용은?" 같은 구어체를 검색어로 정규화
- **Reranker** 가 dense 유사도보다 정교하게 top-5 선별
- **한국어 형태소 분석(Nori)** — 조사/어미 처리로 한국어 recall↑

## 3. Sonar의 실제 운영 설정 (약점)

- namespace `6a44a712…` 실측: **hybrid=False, reranking=False, top_k=4, alpha=0.5**
- 즉 **순수 dense(ada-002) top-4** — bari의 4단계 중 "dense baseline" 하나만 쓰는 셈
- 쿼리 재작성/BM25/reranker **전부 미사용**

**→ 이것이 KSPO 챗봇이 "위치/비용" 질문에 `<NOANS>` 내는 직접 원인.**
실측: "체력측정 비용은?"은 답 청크가 top-5에 안 옴 → NOANS.
     "국민체력100 무료"(정확어)로 물으면 3위에 잡혀 정답.
     top_k 5→10으로 올리자 "테니스장 이용법"은 즉시 정답.

## 4. 중요한 반전 — 데이터 품질은 KSPO(우리)가 우위

검색 *엔진*은 bari가 낫지만, **적재된 데이터 품질**은 우리(KSPO ingest)가 더 정제돼 있다:
- http/https 쌍둥이 중복 제거, LLM 정제 요약, quality gate, known-facts 층
- bari는 사내문서(PDF) 대상이라 코퍼스 성격이 다름 — 직접적 우열보다 "설계 사상" 비교가 맞다

## 5. Sonar 검색을 bari 수준으로 끌어올리는 실행안 (비용순)

| 단계 | 조치 | 효과 | 방법 |
|---|---|---|---|
| **1** | top_k 4→10 | 즉효 (테니스 등 다수 해결) | namespace preview_settings 수정 |
| **2** | **hybrid=True** (SPLADE sparse 켜기) | "비용/주소" 정확어 recall↑ | namespace hybrid=true + TEI sparse 서버 |
| **3** | **reranking=True** (bge-reranker) | top-5 정밀도↑ | namespace reranking 설정 |
| **4** | 핵심 팩트 문서 추가 | 주소·대표전화 확실한 답변 | 우리 known-facts를 KB 단독문서로 |

Sonar는 2·3의 코드가 **이미 있으므로**(sparse_encoders.py, reranker.py), TEI 임베딩/reranker 서버만 붙이고 namespace 플래그만 켜면 bari와 동급 하이브리드가 된다.

## 6. 정량 비교를 하려면
동일 평가셋에서 stage별 nDCG@5/Recall@10 측정이 정답. bari엔 `evaluation/` 벤치가
이미 있으니, KSPO 골든셋(`docs/operations/07_rag_evaluation_dataset.md`, 50문항)을
BEIR 포맷으로 변환해 양쪽에 돌리면 숫자로 우열이 나온다.

## 부록: 소스 위치
- bari: `src/search/{hybrid,query_rewriter,reranker}.py`, `src/rag/pipeline.py`, `evaluation/`
- Sonar: `sonar-llm/tilellm/store/qdrant/qdrant_repository_local.py`(hybrid),
  `tilellm/tools/{sparse_encoders,reranker}.py`, `tilellm/models/llm.py`(파라미터)
