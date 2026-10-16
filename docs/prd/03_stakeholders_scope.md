# PRD §2 — 이해관계자 · §3 — 범위

> 본 파일: PRD **§2 + §3**. 전체 인덱스: [00_index.md](./00_index.md)
> 작성: 2026-05-07 / 상태: draft v1.4

---

## 2. 이해관계자 · RACI

### 2.1 발주·소유

- **발주처·운영 주체**: 국민체육진흥공단(KSPO) ✓
- **개발 위탁사**: 무한아이티 ✓
- **사후 지원**: 무한아이티 — 버그 수정만, 6개월 ✓

### 2.2 챗봇·검색

- **Tiledesk 인스턴스 운영**: KSPO 자체 온프레미스 (Tiledesk Compose 직접 운영) ✓
- **챗봇 노출**: KSPO 메인 사이트(`kspo.or.kr`) 위젯 ✓
- **주 사용자**: 일반 국민 (외부 민원 응대) ✓
- **챗봇 개통 시점**: 본 시스템 완료 후 ✓

### 2.3 RACI 표

| 활동 | KSPO Admin | KSPO IT | 무한아이티 | Tiledesk |
|---|:-:|:-:|:-:|:-:|
| 도메인 등록 | **R, A** | I | I | — |
| 콘텐츠 검수 (PII 수동 제거 등) | **R, A** | I | C (6개월) | — |
| Job 모니터링·재시도 | **R, A** | I | C (6개월) | — |
| 장애 1차 대응 | **R** | **A** | C (6개월) | — |
| 버그 수정 | I | A (인수 후) | **R** (6개월 한정) | — |
| 비용·카드 관리 | **A** | I | — | — |
| Tiledesk 인스턴스 운영 | I | **R, A** | — | — |
| 보안·접근통제 | I | **R, A** | C | — |

> R = Responsible(실행), A = Accountable(책임), C = Consulted(자문), I = Informed(통지)

---

## 3. 범위

### 3.1 In-scope

- KSPO 본사이트·패밀리 사이트의 **공개 페이지** 자동 수집·정제·벡터화
- Qdrant Direct 모드 적재
- 첨부 다운로드·텍스트 추출(PDF/DOCX/XLSX/PPTX)
- 단일 Admin React SPA 운영 콘솔 (5페이지)

### 3.2 Out-of-scope

- 챗봇 UI 구현 (Tiledesk 위젯 사용)
- Tiledesk-LLM 컨테이너 운영 (KSPO 별도 Compose)
- OCR (스캔 PDF) — Tier 3
- HWP 본문 추출 ✓ — 첨부 메타만 기록(`extraction_status='SKIPPED'`), 본문 추출 안 함
- 카테고리 사전·룰엔진·SimHash 등 — Tier 2/3 (`docs/design/_appendix.md` §C)

### 3.3 콘텐츠 자격

- **공개 자료 한정** — 로그인 없는 페이지만 크롤하므로 모두 공개자료로 간주 ✓
- **개인정보 노출** 발견 시 — Admin이 `deny_patterns` / 페이지 수동 제거 (자동 마스킹 미도입) ✓
- 크롤 대상 도메인 — 사전 명시 안 함, **Admin이 운영 시점에 root 도메인 등록** ✓

### 3.4 첨부 처리

- 지원: PDF / DOCX / XLSX / PPTX
- 미지원: HWP, ZIP, 이미지(OCR 미포함)
- 100MB 상한
- 본문 추출 실패 시: `extraction_status='ERROR'` 기록, 다운로드 링크는 유지

---

이전: [§1 개요](./02_overview.md) · 다음: [§4 솔루션](./04_solution.md)
