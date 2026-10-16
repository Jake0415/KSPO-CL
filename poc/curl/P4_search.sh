#!/usr/bin/env bash
# P4 — End-to-end 검색 검증 (우리 Direct 경로로 적재 → /api/qa로 검색 도달 확인)
# 산출: poc/captures/P4_search.json
#
# 사전조건: P1 결과로 payload 키 컨벤션 확정됨.
# 본 스크립트는 LangChain 표준 (page_content + metadata) 가정으로 작성되었으므로
# P1 결과가 다르면 -d 본문 키를 보정한다.
set -euo pipefail

: "${TILELLM:?must set TILELLM}"
: "${TOKEN:?must set TOKEN}"
: "${QDRANT:?must set QDRANT}"
: "${INDEX_NAME:=tilellm}"

OUT_DIR="$(dirname "$0")/../captures"
mkdir -p "$OUT_DIR"

# 3072 차원 더미 벡터 (실제 임베딩 호출 대신 OpenAI에서 받은 값으로 교체 권장)
echo "[P4-0] 더미 3072 차원 벡터 생성 (실제 검증은 OpenAI 임베딩 응답 사용 권장)"
DUMMY_VECTOR=$(python -c "import json; print(json.dumps([0.01]*3072))")

POINT_ID="$(python -c "import uuid; print(uuid.uuid4())")"
echo "[P4-1] Qdrant Direct upsert (P1 키 컨벤션 그대로) — point_id=$POINT_ID"

REQ=$(python <<EOF
import json, sys
req = {
  "points": [{
    "id": "$POINT_ID",
    "vector": $DUMMY_VECTOR,
    "payload": {
      "page_content": "[제목] PoC P4 검증\n[도메인] www.kspo.or.kr\n\n— 본문 —\n이 문서는 본 시스템 Direct 어댑터가 적재한 P4 검증용 데이터입니다.",
      "metadata": {
        "id": "p4-poc-1",
        "source": "https://www.kspo.or.kr/poc-p4",
        "namespace": "kspo",
        "type": "text",
        "domain_host": "www.kspo.or.kr",
        "title": "PoC P4 검증",
        "embedding_version": 1,
        "is_attachment": False,
        "tags": ["d:www.kspo.or.kr","p:2026","is_att:0","v:1"]
      }
    }
  }]
}
print(json.dumps(req, ensure_ascii=False))
EOF
)

curl -fsS -X PUT "$QDRANT/collections/$INDEX_NAME/points?wait=true" \
  -H "Content-Type: application/json" \
  -d "$REQ" > "$OUT_DIR/P4_upsert_response.json"
echo "  upsert OK"

echo "[P4-2] Tiledesk-LLM /api/qa 검색"
curl -fsS -X POST "$TILELLM/api/qa" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"question\":\"PoC P4 검증\",\"namespace\":\"kspo\",\"top_k\":3,\"engine\":{\"name\":\"qdrant\",\"url\":\"$QDRANT\",\"index_name\":\"$INDEX_NAME\"}}" \
  > "$OUT_DIR/P4_search.json"

echo
echo "[P4] 응답:"
cat "$OUT_DIR/P4_search.json" | python -m json.tool || cat "$OUT_DIR/P4_search.json"
echo
echo "[P4] 확인:"
echo "  - sources[].source 에 'https://www.kspo.or.kr/poc-p4' 등장하면 PASS"
echo "  - 응답 텍스트가 우리 본문을 인용하면 PASS"
echo "  - 실패 시 P1 결과로 키 컨벤션 재검토 → 본 스크립트 -d 본문 보정"
