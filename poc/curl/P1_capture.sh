#!/usr/bin/env bash
# P1 — Tiledesk 적재 후 Qdrant payload 키 컨벤션 캡처
# 산출: poc/captures/P1_payload.json
set -euo pipefail

: "${TILELLM:?must set: export TILELLM=http://localhost:8000}"
: "${TOKEN:?must set: export TOKEN=...}"
: "${QDRANT:?must set: export QDRANT=http://localhost:6333}"
: "${INDEX_NAME:=tilellm}"

OUT_DIR="$(dirname "$0")/../captures"
mkdir -p "$OUT_DIR"

echo "[P1] 1건 적재 → $TILELLM/api/ingestion"
curl -fsS -X POST "$TILELLM/api/ingestion" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"id\": \"poc-payload-1\",
    \"type\": \"text\",
    \"content\": \"이것은 PoC 테스트입니다. 본문 텍스트가 어느 키로 저장되는지 확인.\",
    \"source\": \"https://example.com/poc-p1\",
    \"namespace\": \"poc_payload\",
    \"embedding\": \"text-embedding-3-large\",
    \"engine\": {\"name\":\"qdrant\",\"url\":\"$QDRANT\",\"index_name\":\"$INDEX_NAME\"}
  }" | tee "$OUT_DIR/P1_ingestion_response.json"
echo

echo "[P1] Qdrant scroll로 1건 포인트 조회 → $OUT_DIR/P1_payload.json"
curl -fsS -X POST "$QDRANT/collections/$INDEX_NAME/points/scroll" \
  -H "Content-Type: application/json" \
  -d '{"limit": 1, "with_payload": true, "with_vector": false}' \
  > "$OUT_DIR/P1_payload.json"

echo
echo "[P1] 결과:"
cat "$OUT_DIR/P1_payload.json" | python -m json.tool || cat "$OUT_DIR/P1_payload.json"
echo
echo "[P1] 확인할 것 (report.md에 기록):"
echo "  - 본문 텍스트 키: page_content / text / content / 기타?"
echo "  - 메타 위치: metadata.{...} 중첩 / 평면(flat)?"
echo "  - 키: id, source, namespace, type, tags 보존 형태"
echo "  - LangChain 표준(page_content + metadata) 일치 여부"
