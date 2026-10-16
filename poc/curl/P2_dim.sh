#!/usr/bin/env bash
# P2 — 차원 호환성 (text-embedding-3-large 3072)
# 산출: poc/captures/P2_dims.json
set -euo pipefail

: "${TILELLM:?must set TILELLM}"
: "${TOKEN:?must set TOKEN}"
: "${QDRANT:?must set QDRANT}"
: "${INDEX_NAME:=tilellm}"

OUT_DIR="$(dirname "$0")/../captures"
mkdir -p "$OUT_DIR"

echo "[P2-1] 기존 컬렉션($INDEX_NAME) 차원 확인"
DEFAULT_DIM=$(curl -fsS "$QDRANT/collections/$INDEX_NAME" | python -c "import json,sys; print(json.load(sys.stdin)['result']['config']['params']['vectors'].get('size','UNKNOWN'))")
echo "  default dim: $DEFAULT_DIM"

INDEX_3L="${INDEX_NAME}_3l_poc"
echo "[P2-2] 3072 모델로 새 컬렉션($INDEX_3L) 적재"
curl -fsS -X POST "$TILELLM/api/ingestion" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"id\":\"poc-3l-1\",
    \"type\":\"text\",
    \"content\":\"3072 차원 호환성 테스트\",
    \"source\":\"https://example.com/poc-p2\",
    \"namespace\":\"poc_3l\",
    \"embedding\":\"text-embedding-3-large\",
    \"engine\":{\"name\":\"qdrant\",\"url\":\"$QDRANT\",\"index_name\":\"$INDEX_3L\"}
  }" > "$OUT_DIR/P2_ingestion_response.json"

THREE_L_DIM=$(curl -fsS "$QDRANT/collections/$INDEX_3L" | python -c "import json,sys; print(json.load(sys.stdin)['result']['config']['params']['vectors'].get('size','UNKNOWN'))")
echo "  $INDEX_3L dim: $THREE_L_DIM"

cat > "$OUT_DIR/P2_dims.json" <<EOF
{
  "default_index_name": "$INDEX_NAME",
  "default_dim": $DEFAULT_DIM,
  "three_large_index_name": "$INDEX_3L",
  "three_large_dim": $THREE_L_DIM,
  "expected": 3072,
  "pass": $([ "$THREE_L_DIM" = "3072" ] && echo true || echo false)
}
EOF

cat "$OUT_DIR/P2_dims.json" | python -m json.tool
echo
echo "[P2] 확인:"
echo "  - 첫 적재가 차원을 결정하는지 (yes/no)"
echo "  - 3072가 정상 만들어지면 PASS, 아니면 text-embedding-3-small(1536) 폴백 검토"
