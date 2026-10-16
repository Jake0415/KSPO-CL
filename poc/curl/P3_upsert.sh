#!/usr/bin/env bash
# P3 — Upsert + Delete 동작 검증
# 산출: poc/captures/P3_upsert.txt
set -euo pipefail

: "${TILELLM:?must set TILELLM}"
: "${TOKEN:?must set TOKEN}"
: "${QDRANT:?must set QDRANT}"
: "${INDEX_NAME:=tilellm}"

OUT_DIR="$(dirname "$0")/../captures"
mkdir -p "$OUT_DIR"
LOG="$OUT_DIR/P3_upsert.txt"
: > "$LOG"

log() { echo "$@" | tee -a "$LOG"; }

log "[P3-1] 같은 id로 v1 적재"
curl -fsS -X POST "$TILELLM/api/ingestion" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"id\":\"poc-up-1\",\"type\":\"text\",\"content\":\"버전1 본문\",\"namespace\":\"poc_up\",\"embedding\":\"text-embedding-3-large\",\"engine\":{\"name\":\"qdrant\",\"url\":\"$QDRANT\",\"index_name\":\"$INDEX_NAME\"}}" \
  >> "$LOG"
echo >> "$LOG"

log "[P3-2] 같은 id로 v2 재적재 (upsert 검증)"
curl -fsS -X POST "$TILELLM/api/ingestion" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"id\":\"poc-up-1\",\"type\":\"text\",\"content\":\"버전2 본문 (변경됨)\",\"namespace\":\"poc_up\",\"embedding\":\"text-embedding-3-large\",\"engine\":{\"name\":\"qdrant\",\"url\":\"$QDRANT\",\"index_name\":\"$INDEX_NAME\"}}" \
  >> "$LOG"
echo >> "$LOG"

log "[P3-3] 검색으로 본문이 v2인지 확인"
curl -fsS -X POST "$TILELLM/api/qa" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"question\":\"버전\",\"namespace\":\"poc_up\",\"top_k\":1,\"engine\":{\"name\":\"qdrant\",\"url\":\"$QDRANT\",\"index_name\":\"$INDEX_NAME\"}}" \
  >> "$LOG"
echo >> "$LOG"

log "[P3-4] Tiledesk wrapper 삭제 API (정확 명칭은 OpenAPI에서 확인 — 후보 2종)"
log "  후보1: POST /api/delete/id"
curl -fsS -X POST "$TILELLM/api/delete/id" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"id":"poc-up-1","namespace":"poc_up"}' >> "$LOG" 2>&1 || log "  → 4xx (지원 안 함 가능)"
echo >> "$LOG"

log "[P3-5] Qdrant Direct 필터 삭제 (우회 — 본 시스템이 사용할 경로)"
curl -fsS -X POST "$QDRANT/collections/$INDEX_NAME/points/delete" \
  -H "Content-Type: application/json" \
  -d '{"filter":{"must":[{"key":"metadata.id","match":{"value":"poc-up-1"}}]},"wait":true}' \
  >> "$LOG"
echo >> "$LOG"

log "[P3-6] 삭제 후 재검색 — 결과 0건 또는 다른 id"
curl -fsS -X POST "$TILELLM/api/qa" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"question\":\"버전\",\"namespace\":\"poc_up\",\"top_k\":1,\"engine\":{\"name\":\"qdrant\",\"url\":\"$QDRANT\",\"index_name\":\"$INDEX_NAME\"}}" \
  >> "$LOG"
echo >> "$LOG"

log
log "[P3] 결정:"
log "  - 같은 id 재적재 = upsert (PASS) 또는 우회 시퀀스 결정"
log "  - 단건/필터 삭제 가능 여부 결정"
log "  - 키 경로(metadata.id vs id, metadata.tags vs tags) — P1 결과에 따라 조정"

echo "[P3] 완료 — 결과는 $LOG"
