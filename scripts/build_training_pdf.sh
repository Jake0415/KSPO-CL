#!/usr/bin/env bash
# 교육 슬라이드 PDF 빌드 — marp-cli (Markdown → PDF/PPTX)
#
# 사전 조건:
#   - npm install -g @marp-team/marp-cli
#   또는 npx 사용:
#     npx -y @marp-team/marp-cli@latest
#
# 사용법:
#   bash scripts/build_training_pdf.sh
#   make training-pdf
#
# 출력: dist/training/*.pdf (4세트) + dist/training/all.pdf (합본)

set -euo pipefail

cd "$(dirname "$0")/.."

OUT_DIR=dist/training
mkdir -p "$OUT_DIR"

MARP="${MARP:-npx -y @marp-team/marp-cli@latest}"

# 4 세트 개별 PDF
for f in docs/training/*.md; do
  name=$(basename "$f" .md)
  $MARP --pdf "$f" -o "$OUT_DIR/${name}.pdf"
done

# 합본 PDF — 4세트 markdown을 단일 marp 문서로 결합
COMBINED=dist/training/_all.md
{
  cat docs/training/00_intro.md
  echo
  echo "---"
  echo
  cat docs/training/01_admin_daily.md
  echo
  echo "---"
  echo
  cat docs/training/02_runbook_walkthrough.md
  echo
  echo "---"
  echo
  cat docs/training/03_qna.md
} > "$COMBINED"

$MARP --pdf "$COMBINED" -o "$OUT_DIR/kspo-ingest_교육슬라이드_v2.1.pdf"

echo "✓ $OUT_DIR/ 생성 완료"
ls -la "$OUT_DIR"
