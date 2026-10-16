# 03. 청킹 + 임베딩 + Qdrant Direct 적재

## 3.1 책임 범위

REFINED 페이지(또는 첨부)를 입력받아 청킹 → OpenAI 임베딩 호출 → **Qdrant에 Direct upsert** (개발/파일럿: 자체 컨테이너 / 정식 운영: Tiledesk 외부 인스턴스 — `QDRANT_URL` 토글로 전환).
PG `chunks`로 메타 추적, 본문은 Qdrant payload에만.

## 3.2 청킹 — 2단

```python
CHUNK_LONG_THRESHOLD_TOKENS = 800
CHUNK_TARGET_TOKENS = 600
CHUNK_OVERLAP_TOKENS = 80

if tokens(body) > 800:
    chunks = window_split(body, target=600, overlap=80)
else:
    chunks = [body]
```

토크나이저는 `tiktoken`. 분할 단위는 `\n\n` > `\n` > `. ? !` > 어절. **헤딩 우선 분할은 Tier 2**.

## 3.3 컨텍스트 헤더 — 고정 1종

모든 청크에 동일 포맷의 헤더를 prepend.

```
[제목] 2026년 일반사업 공모 공고
[도메인] www.kspo.or.kr
[게시일] 2026-04-20
[요약] KSPO가 2026년 일반사업 공모를 공고. 접수 5/1~5/31. 첨부 '공고문.pdf' 참조.

— 본문 —
국민체육진흥공단은 ...
```

`posted_at` / `summary` 없으면 해당 라인 생략. 헤더 토큰 가드 미운영(Tier 2).

> v1.0의 적응형 헤더(표준/확장/강화) 제거. 짧은 페이지의 검색 품질이 측정상 부족하면 Tier 2에서 부활.

## 3.4 첨부 청크

부모 게시글과 별도 청크 그룹. 헤더에 첨부파일명·부모 게시글 정보 포함.

```
[첨부파일] 공고문.pdf
[부모 게시글] 2026년 일반사업 공모 공고
[게시일] 2026-04-20

— 본문 —
...
```

## 3.5 임베딩

- 모델: `text-embedding-3-large` (3072 dims). 환경변수 `OPENAI_EMBED_MODEL`
- 배치: input 배열 최대 96 청크
- 비용: `llm_usage.purpose='embedding'`
- 부분 실패 시 1건씩 분리 재호출 → 그래도 실패면 `chunks.embed_status='ERROR'`

## 3.6 Deterministic Chunk ID

```python
import uuid, hashlib
NAMESPACE_KSPO = uuid.UUID("8c2a6e2e-0a3f-4b7d-9c54-1f1c5a2e1b00")

def chunk_id_sha1(page_id, embedding_version, chunk_index, is_attachment, attachment_id):
    s = f"{page_id}|{embedding_version}|{chunk_index}|{int(is_attachment)}|{attachment_id or 0}"
    return hashlib.sha1(s.encode()).hexdigest()

def to_qdrant_point_id(chunk_id_sha1: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE_KSPO, chunk_id_sha1)
```

같은 입력 → 같은 ID → upsert 자연 동작.

## 3.7 chunks 테이블 (단순화)

```sql
CREATE TABLE chunks (
  id BIGSERIAL PRIMARY KEY,
  chunk_id_sha1 CHAR(40) NOT NULL,
  qdrant_point_id UUID NOT NULL,
  page_id BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  attachment_id BIGINT REFERENCES attachments(id) ON DELETE CASCADE,
  is_attachment BOOLEAN NOT NULL DEFAULT FALSE,
  chunk_index INTEGER NOT NULL,
  token_len INTEGER NOT NULL,
  embedding_model TEXT NOT NULL,
  embedding_version INTEGER NOT NULL DEFAULT 1,
  embed_status TEXT NOT NULL DEFAULT 'PENDING',
  kb_status TEXT NOT NULL DEFAULT 'PENDING',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (page_id, embedding_version, chunk_index, is_attachment, attachment_id)
);
CREATE INDEX idx_chunks_page ON chunks(page_id);
CREATE INDEX idx_chunks_qdrant ON chunks(qdrant_point_id);
CREATE INDEX idx_chunks_kb_status ON chunks(kb_status);
```

> v1.0 대비 빠진 컬럼: `simhash`, `text_sha256`, `dup_group_id`, `section_path`, `namespace`, `char_len`. SimHash dedup 자체를 Tier 2로 이동.

본문 텍스트는 PG에 저장 안 함. 디버깅용 `storage/refined/.../chunks.jsonl`에 보관.

## 3.8 Qdrant 컬렉션

| 항목 | 값 |
|---|---|
| 이름 | `QDRANT_INDEX_NAME` 환경변수 (개발/파일럿: 임의 — 예 `kspo_dev` / 정식: Tiledesk가 사용하는 `index_name`, 예 `tilellm`) |
| 차원 | 3072 (text-embedding-3-large) — PoC로 확정 |
| 거리 | Cosine |
| 저장 | vectors `on_disk=true`, scalar int8 quantization |

부팅 시 `KB_BOOTSTRAP=managed`이면 본 시스템이 컬렉션 존재·차원 검증. 차원 mismatch면 `/readyz` 503 + 운영자 알림.

**듀얼 모드 동작**:
- 개발/파일럿: 자체 `qdrant` 컨테이너에 컬렉션 자동 생성. 차원 mismatch 발생 가능성 낮음
- 정식 운영: Tiledesk가 이미 만든 컬렉션을 외부에서 가리킴. 차원·payload 키 컨벤션이 사전과 일치하지 않으면 PoC P1~P4 재검증 후 어댑터 보정

## 3.9 Payload 스키마 — Tiledesk-LLM 호환

> 정확한 키 컨벤션은 PoC #1 결과로 확정. 아래는 LangChain Qdrant 어댑터 표준 가정.

```json
{
  "page_content": "<헤더 + 본문>",
  "metadata": {
    "id": "<chunk_id_sha1>",
    "source": "https://www.kspo.or.kr/bbs/view.do?nttId=12345",
    "namespace": "kspo",
    "type": "text",
    "domain_host": "www.kspo.or.kr",
    "title": "...",
    "summary": "...",
    "keywords": ["..."],
    "posted_at": "2026-04-20T00:00:00Z",
    "last_indexed_at": "2026-05-06T12:00:00Z",
    "is_attachment": false,
    "attachment_id": null,
    "attachment_name": null,
    "attachment_download_url": null,
    "parent_page_id": null,
    "parent_page_url": null,
    "embedding_version": 1,
    "tags": [
      "d:www.kspo.or.kr","p:2026","p:2026-04",
      "att:0","is_att:0","v:1"
    ]
  }
}
```

v1.0 대비 빠진 키: `categories`/`category_ids`, `language`, `quality_score`, `is_meaningful`, `is_metadata_only`, `dup_group_id`/`canonical`, `rule_id`/`rule_type`, `boilerplate_version`, `last_modified_at`.

## 3.10 Tags 컨벤션 (단순화)

| Prefix | 의미 | 예 |
|---|---|---|
| `d:` | domain_host | `d:www.kspo.or.kr` |
| `p:` | posted_at 연·연월 | `p:2026` / `p:2026-04` |
| `att:` | attachment_id | `att:987` |
| `pid:` | parent_page_id | `pid:12345` |
| `is_att:` | 첨부 청크 | `is_att:1` |
| `v:` | embedding_version | `v:1` |

v1.0 대비 빠진 prefix: `c:`, `lang:`, `ru:`, `rt:`, `meta_only:`, `dup:`, `qs:`, `bp:`, `lm:`. 카테고리/룰/언어 기반 필터는 Tier 2.

## 3.11 Payload 인덱스

| 필드 | 타입 |
|---|---|
| `metadata.domain_host` | keyword |
| `metadata.posted_at` | datetime |
| `metadata.last_indexed_at` | datetime |
| `metadata.is_attachment` | bool |
| `metadata.parent_page_id` | integer |
| `metadata.embedding_version` | integer |
| `metadata.tags` | keyword |

## 3.12 Direct 어댑터 인터페이스

```python
class QdrantDirectAdapter:
    namespace: str = "kspo"

    async def ensure_collection(self) -> None: ...
    async def upsert_chunks(self, points: list[EmbeddedChunk]) -> UpsertResult: ...
    async def delete_by_ids(self, ids: list[uuid.UUID]) -> None: ...
    async def delete_by_domain(self, domain_host: str) -> int: ...   # filter delete
    async def replace_page_chunks(
        self, page_id: int, version: int, new_points: list[EmbeddedChunk]
    ) -> SyncResult: ...
```

## 3.13 워크플로

```
[Refiner] is_meaningful=true → ARQ 'chunk_and_embed' enqueue
[Embed Worker]
  1) load refined JSON
  2) build chunks (3.2 ~ 3.4)
  3) PG chunks 'PENDING' upsert
  4) 배치 임베딩 호출
  5) llm_usage(purpose='embedding')
  6) Qdrant Direct upsert + 옛 청크 cleanup
  7) chunks.kb_status='OK', pages.status='INDEXED'
  8) 실패 시 ERROR + 다음 incremental 재시도
```

## 3.14 청크 동기화 (재크롤 후)

같은 page_id의 옛 청크 ID와 새 청크 ID를 diff:
- 신규: upsert
- 사라진: Qdrant delete_by_ids
- 동일 id에 본문 변경: upsert (자연 갱신)

PG `chunks`는 새 set으로 replace.

## 3.15 챗봇 측 검색 (참고, 본 시스템 범위 외)

```http
POST /api/qa
{
  "question": "2026 일반사업 공모 접수기간은?",
  "namespace": "kspo",
  "top_k": 8,
  "tags": ["d:www.kspo.or.kr"],
  "engine": {"name":"qdrant","url":"http://qdrant:6333","index_name":"tilellm"}
}
```

응답의 `sources[].source`(URL)와 `metadata.attachment_*`를 챗봇이 사용자에게 노출. 본 시스템은 이 경로에 관여 안 함.
