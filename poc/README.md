# PoC 작업 가이드

`checklist.md`의 P1~P4를 1~2일 내 검증하기 위한 실행 디렉터리.

## 디렉터리 구조

```
poc/
├─ checklist.md           # P1~P4 명세 (단일 진실원)
├─ README.md              # 본 파일
├─ curl/                  # 실행 스크립트 4종
│   ├─ P1_capture.sh
│   ├─ P2_dim.sh
│   ├─ P3_upsert.sh
│   └─ P4_search.sh
├─ captures/              # 결과 산출물 (.json/.txt)
│   └─ (P1_payload.json, P2_dims.json, P3_upsert.txt, P4_search.json)
└─ report.md              # 최종 1장 보고서 (템플릿 → 실행 후 채움)
```

## 실행 절차

### 1. 환경 변수 설정

```bash
# Tiledesk-LLM이 띄워둔 host:port
export TILELLM=http://localhost:8000

# JWT 토큰 (Tiledesk-LLM의 JWT_SECRET_KEY로 발급)
export TOKEN="$(python -c 'import jwt; print(jwt.encode({"sub":"poc"}, "YOUR_JWT_SECRET"))')"

# Tiledesk가 가리키는 Qdrant
export QDRANT=http://localhost:6333

# 컬렉션 이름 (Tiledesk가 사용하는 것 — 보통 'tilellm')
export INDEX_NAME=tilellm
```

### 2. P1~P4 순차 실행

```bash
bash poc/curl/P1_capture.sh   # → poc/captures/P1_payload.json
bash poc/curl/P2_dim.sh       # → poc/captures/P2_dims.json
bash poc/curl/P3_upsert.sh    # → poc/captures/P3_upsert.txt
bash poc/curl/P4_search.sh    # → poc/captures/P4_search.json
```

각 스크립트는 결과를 stdout으로도 출력하므로 직접 검토 가능.

### 3. 보고서 작성

`report.md`의 빈칸을 P1~P4 결과로 채움. 결정 사항 5종(payload 키 / 차원 / upsert / delete / 검색 동작)을 확정.

### 4. 본 시스템 적용

`report.md`가 정리되면:
- `docs/design/03_chunk_embed_qdrant.md` §3.9 (payload 스키마)와 일치하는지 확인
- 일치하지 않으면 `src/kspo_ingest/qdrant/payload.py`의 `build_payload()` 수정 (M3.T3.3 시점)
- 코드 진입(`docs/tasks/M0_T0_1.md`)은 PoC 결과와 무관하게 시작 가능 (자체 Qdrant로 진행, 정식 전환 시 PoC 재검증)

## 진입 조건

- Tiledesk Compose 가동 (`tiledesk-llm` + Qdrant)
- `OPENAI_API_KEY` 설정 (PoC 비용 ≤ $1)
- 본 시스템 환경: `kspo-ingest` Compose는 미가동 상태로도 PoC 가능

## 미가용 시 결정

PRD §4.2 / `00_roadmap.md` §3.1: 파일럿까지는 자체 Qdrant 컨테이너로 진행하므로 PoC를 미리 못 해도 M0~M4 진행 가능. 단 정식 운영 전환 직전에 P1~P4 **재검증 의무**.
