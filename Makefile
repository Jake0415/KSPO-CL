# kspo-ingest — 빌드 자동화 (PDF/문서)
#
# 사전 조건:
#   make pdf          → pandoc + xelatex (TeX Live full + Noto Sans CJK KR)
#   make training-pdf → marp-cli (Node.js + npx)
#
# 운영 코드 빌드는 docker compose가 담당 — 본 Makefile은 인계 산출물 전용.

.PHONY: pdf training-pdf docs all clean help

help:
	@echo "사용 가능 타겟:"
	@echo "  make pdf           - 운영 매뉴얼 PDF 빌드 (dist/kspo-ingest_운영매뉴얼_v2.1.pdf)"
	@echo "  make training-pdf  - 교육 슬라이드 PDF 빌드 (dist/training/)"
	@echo "  make docs          - 위 두 개 모두 빌드"
	@echo "  make clean         - dist/ 디렉터리 삭제"

pdf:
	@bash scripts/build_pdf.sh

training-pdf:
	@bash scripts/build_training_pdf.sh

docs: pdf training-pdf

all: docs

clean:
	rm -rf dist/
