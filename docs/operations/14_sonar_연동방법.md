# Sonar(tiledesk-llm) 챗봇 연동 방법 — 확정

> 목적: KSPO 크롤 데이터를 Sonar 챗봇이 실제로 검색·답변에 쓰게 하는 정확한 방법.
> Sonar 소스(`/Users/yeonsu/2026/Sonar/sonar-llm`) 직접 분석 결과.

## 결론 요약
- 우리가 운영 Qdrant(`223.130.163.224:6333`)에 넣은 `tilellm`(3072차원, OpenAI large)은
  **Sonar가 그대로 쓸 수 없다.** Sonar는 자체 임베딩(기본 `text-embedding-ada-002`
  1536차원, 또는 TEI e5/bge-m3 1024) + **sparse(SPLADE) 하이브리드** + **namespace** 구조를 쓴다.
- **올바른 방법: Sonar의 적재 API(`POST /api/scrape/single`)에 우리 "텍스트"를 던진다.**
  그러면 Sonar가 자기 임베딩·sparse·namespace로 알아서 인덱싱한다. 우리는 Qdrant에
  직접 안 넣는다.

## Sonar 적재 API — `POST /api/scrape/single`

### 핵심: 이미 정제된 텍스트를 직접 넣을 수 있다
`ItemSingle` 스키마에 `content` 필드가 있고, ingestion controller가
`file_content = item.source or item.content` 로 처리한다. 즉 **`content`에 우리
정제 텍스트를 넣으면 재크롤 없이 그대로 인덱싱**된다. (`source`에 URL을 넣으면 Sonar가
직접 크롤; 우리는 이미 크롤·정제했으므로 `content` 사용)

### 요청 바디 (ItemSingle) — 우리가 채울 필드
```json
{
  "id": "<우리 chunk_id 또는 page 식별자>",
  "content": "<정제된 본문 텍스트 (제목+본문)>",
  "source": "https://www.kspo.or.kr/...",   // 출처 URL (표시·인용용)
  "type": "text",
  "namespace": "kspo",                       // ★ 데이터 구분 키 (Sonar는 namespace로 격리)
  "scrape_type": 3,                          // content 직접 사용 (URL 크롤 아님)
  "embedding": "text-embedding-ada-002",     // ★ Sonar 기본 — 서버 실제 설정에 맞출 것
  "hybrid": true,                            // sparse 하이브리드 사용 시
  "sparse_encoder": "splade",
  "gptkey": "<OpenAI 키 — 임베딩용>",
  "tags": ["d:www.kspo.or.kr", "v:1"],
  "engine": {
    "name": "qdrant",
    "deployment": "local",
    "host": "sonar-qdrant-1",   // 서버 내부에서는 컨테이너명, 외부에선 223.130.163.224
    "port": 6333,
    "index_name": "tilellm",    // Sonar 컬렉션명 (서버 실제값 확인 필요)
    "vector_size": 1536,        // ★ 임베딩 모델 차원과 반드시 일치
    "metric": "cosine"
  }
}
```

### 반드시 서버에서 확정할 값 (3가지)
1. **embedding 모델** — 서버 Sonar가 실제 뭘 쓰는지. `ada-002`(1536)? TEI e5(1024)?
   → 기존 `tiledesk-llm` 컬렉션이 1536이었으므로 **ada-002(1536)일 가능성 높음**.
2. **namespace 값** — KSPO 챗봇이 읽는 namespace 이름. (대시보드 프로젝트ID
   `6a44a712...`가 namespace일 수 있음 → Sonar 관리자에서 확인)
3. **index_name(컬렉션)** — Sonar가 그 namespace를 어느 컬렉션에 저장하는지.

## 검증 방법 (연동 확인)
Sonar에 넣은 뒤, Sonar 자체 QA API로 확인:
```bash
curl -s -X POST http://223.130.163.224:8000/api/qa \
  -H "Content-Type: application/json" \
  -d '{"question":"올림픽수영장 이용 요금은?","namespace":"kspo","gptkey":"<KEY>","embedding":"text-embedding-ada-002","top_k":5}'
```
→ 우리 데이터에서 답이 나오면 연동 성공.

## 정리: 무엇을 바꿔야 하나
| 항목 | 현재 (우리) | Sonar가 원하는 것 | 조치 |
|---|---|---|---|
| 적재 경로 | Qdrant 직접 upsert | **Sonar `/api/scrape/single`** | 어댑터 스크립트 작성 |
| 임베딩 | OpenAI large 3072 | ada-002 1536 (추정) | Sonar가 재임베딩 (우리는 텍스트만) |
| 검색 구조 | dense only | dense + sparse(SPLADE) | Sonar가 처리 |
| 데이터 구분 | 컬렉션명 | **namespace** | 요청에 namespace 지정 |

## 다음 작업 (연동 어댑터)
우리 DB(pages/chunks)의 정제 텍스트를 읽어 Sonar `/api/scrape/single`로 밀어넣는
배치 스크립트. namespace·embedding·index_name 3값 확정 후 착수 가능.
(우리가 이미 Qdrant에 직접 넣은 `tilellm` 3072 데이터는 Sonar가 안 쓰므로,
정리하거나 무시.)
