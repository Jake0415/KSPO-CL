#!/usr/bin/env bash
# 운영 매뉴얼 PDF 빌드 — pandoc + xelatex (한글 폰트: Noto Sans CJK KR)
#
# 사전 조건:
#   - pandoc (>=2.19)
#   - xelatex (TeX Live full 또는 MikTeX)
#   - Noto Sans CJK KR 폰트 (또는 Pretendard, Apple SD Gothic Neo)
#
# 사용법:
#   bash scripts/build_pdf.sh
#   make pdf   (Makefile 경유)
#
# 출력: dist/kspo-ingest_운영매뉴얼_v2.1.pdf

set -euo pipefail

cd "$(dirname "$0")/.."

OUT=dist/kspo-ingest_운영매뉴얼_v2.1.pdf
mkdir -p dist

COMBINED=dist/_combined.md

{
  echo "% KSPO 적재 시스템 운영 매뉴얼"
  echo "% v2.1"
  echo "% 작성: 무한아이티 / 인계: KSPO IT"
  echo
  echo "# 1. 시스템 개요"
  echo
  cat docs/operations/00_overview.md
  echo
  echo "# 2. Admin 일과"
  echo
  cat docs/operations/01_admin_workflow.md
  echo
  echo "# 3. KSPO IT 운영 작업"
  echo
  cat docs/operations/02_kspo_it_workflow.md
  echo
  echo "# 4. 운영 런북 — 사고 대응"
  echo
  cat docs/runbook/A_kb_dim_mismatch.md
  echo
  cat docs/runbook/B_openai_failure.md
  echo
  cat docs/runbook/C_tiledesk_down.md
  echo
  echo "# 5. 자주 발생하는 문제"
  echo
  cat docs/operations/03_troubleshooting.md
  echo
  echo "# 6. 인수 체크리스트"
  echo
  cat docs/operations/04_handover_checklist.md
  echo
  echo "# 부록 A — 환경변수 일람"
  echo
  echo '```'
  cat .env.example
  echo '```'
  echo
  echo "# 부록 B — 배포 런북"
  echo
  cat docs/runbook/deploy.md
} > "$COMBINED"

pandoc "$COMBINED" \
  --toc --toc-depth=2 \
  --pdf-engine=xelatex \
  -V mainfont="Noto Sans CJK KR" \
  -V monofont="DejaVu Sans Mono" \
  -V geometry:margin=2cm \
  -V documentclass=article \
  -V colorlinks=true \
  -V linkcolor=blue \
  -o "$OUT"

echo "✓ $OUT 생성 완료 ($(du -h "$OUT" | cut -f1))"
