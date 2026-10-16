# PRD §10 — 기술 설계 참조 · §11 — 변경 이력

> 본 파일: PRD **§10 + §11**. 전체 인덱스: [00_index.md](./00_index.md)
> 작성: 2026-05-07 / 상태: draft v1.4

---

## 10. 부록 — 기술 설계 참조

| 영역 | 위치 |
|---|---|
| 시스템 개요 | [docs/design/00_overview.md](../design/00_overview.md) |
| 컴포넌트 토폴로지 | [docs/design/01_architecture.md](../design/01_architecture.md) |
| 파이프라인 (Crawl/Clean/Refine) | [docs/design/02_pipeline.md](../design/02_pipeline.md) |
| 청킹·임베딩·Qdrant | [docs/design/03_chunk_embed_qdrant.md](../design/03_chunk_embed_qdrant.md) |
| 증분·API·Admin UI | [docs/design/04_incremental_admin.md](../design/04_incremental_admin.md) |
| DevOps·운영 | [docs/design/05_devops_ops.md](../design/05_devops_ops.md) |
| DDL 6 테이블 / Tier 2-3 로드맵 | [docs/design/_appendix.md](../design/_appendix.md) |
| 운영 런북 3종 (KB 차원·OpenAI 인증·Tiledesk 다운) | [docs/runbook/](../runbook/) (M0.T0.3 산출) |
| 디자인 시스템 | [design-system/CLAUDE.md](../../design-system/CLAUDE.md) |
| 로드맵 (24 Task) | [docs/tasks/00_roadmap.md](../tasks/00_roadmap.md) |
| Round 1 답변 정리 (ARCHIVE) | [01_questions_round1.md](./01_questions_round1.md) |

---

## 11. 변경 이력

| 일자 | 버전 | 변경 |
|---|---|---|
| 2026-05-07 | v1.0 draft (skeleton) | 절 구조 + round 1 답변 반영. §1·§2.3·§5·§6.1/6.3/6.4·§7.2·§8.1/8.2 미작성 |
| 2026-05-07 | v1.1 draft (Claude 1차 작성) | docx + round 1 기반으로 §1 (배경·목표·기존시스템·KPI 후보), §2.3 (RACI), §5 (NFR 잠정안), §6.1 (호스트 권장 최소), §6.3 (컨테이너 구성), §6.4 (보안), §7.2 (인프라 비용), §8.1 (개발 기간 추정), §8.2 (파일럿 권장) 작성. 추정·권장값에는 "확인 필요" 마크. 실제 미해결은 §9.3 표로 일원화 |
| 2026-05-07 | v1.2 (§9.3 #1 해소) | 프록시 메커니즘 확정 — `HTTPS_PROXY` 표준 환경변수, `.env.example` placeholder, NO_PROXY 기본값, 시작 시 warning 검증. 실제 host:port 값은 운영 시 KSPO 인프라팀이 `.env`에 입력. §6.2 표·§9.3 미해결 항목에서 제거 |
| 2026-05-07 | v1.3 (§9.3 #2 해소) | 카드 한도 소진 운영 명세 확정 — 런북 B.2를 B.2.A(키 무효) / B.2.B(결제 실패) 분기. `_appendix.md` §B.2 확장, `05_devops_ops.md` §5.7 알림표에 "월 누계 80%" 행 추가·"일일 비용" 행 제거. PRD §7.1에 사전 알림 행 추가, §9.3에서 제거 |
| 2026-05-07 | v1.4 (구조 분리) | 단일 파일 `02_prd_v1.md`(438줄)을 토픽별 7파일(`02_overview.md` ~ `08_appendix_changelog.md`) + 인덱스(`00_index.md`)로 분리. 절 번호(§1~§11)는 글로벌 유지 — 외부 문서의 `PRD §X.Y` 참조 모두 안전. design docs 분리 패턴과 일관 |
| 2026-05-07 | v1.5 (정합성·가독성 개선) | (A-1) §8.2 step 1 PoC 대상을 "자체 Qdrant" → "Tiledesk Qdrant (가용 시)"로 정정 — roadmap §3.1 P1~P4 정의와 일치. (A-3) CLAUDE.md `(PRD §4.2)` Direct mode 인용을 `§4.3`으로 분리. (B-1) §1.3 FAQ 유지 항목을 §9.3 #10으로 추적 추가. (B-2) §6.3 잠정 결정 표 위에 "M0.T0.2 머지로 구체화 완료" 안내. (B-3) §10 부록 표에 운영 런북 3종 행 추가, 로드맵 24 Task 정정. (C-2) §1.4 KPI 표 위에 "확정" vs "권장 목표" 안내. (C-3) `01_questions_round1.md`에 ARCHIVE 헤더. roadmap 측에선 (A-2) "23 → 24 Task" 정정, (B-4) weekly cron ↔ 정기 재시작 시간 안전망 명시. CLAUDE.md (C-1) 커버리지 규칙을 백엔드 >80% / UI lint+TS+manual로 분리 |

---

이전: [§9 위험·미해결](./07_risks_open.md) · 처음: [00_index.md](./00_index.md)
