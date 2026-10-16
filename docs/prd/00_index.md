# PRD 인덱스 — KSPO 웹크롤링 → Qdrant 적재 시스템 v1

> 작성: 2026-05-07
> 상태: **draft v1.4 (7파일 분리)**
> 출처: `KSPO_벡터DB_적재시스템_통합설계서_v2.0_Lite.docx` + Round 1·2 답변
> 분리 정책: design docs(`docs/design/`) 패턴과 일관 — 절(§) 번호는 글로벌 유지, 파일은 토픽별

---

## 절 → 파일 매핑

| § | 제목 | 파일 |
|---|---|---|
| 1 | 개요 (배경·목표·KPI) | [02_overview.md](./02_overview.md) |
| 2 | 이해관계자 · RACI | [03_stakeholders_scope.md](./03_stakeholders_scope.md) |
| 3 | 범위 (in/out, 콘텐츠 자격, 첨부 처리) | [03_stakeholders_scope.md](./03_stakeholders_scope.md) |
| 4 | 솔루션 개요 (데이터 흐름, Qdrant 듀얼) | [04_solution.md](./04_solution.md) |
| 5 | 비기능 요구사항 (NFR) | [05_nfr_infra.md](./05_nfr_infra.md) |
| 6 | 인프라 (호스팅·프록시·컨테이너·보안·인증) | [05_nfr_infra.md](./05_nfr_infra.md) |
| 7 | 비용 | [06_cost_schedule.md](./06_cost_schedule.md) |
| 8 | 일정 · 롤아웃 | [06_cost_schedule.md](./06_cost_schedule.md) |
| 9 | 위험 · 가정 · 외부 의사결정 의존 항목 | [07_risks_open.md](./07_risks_open.md) |
| 10 | 기술 설계 참조 | [08_appendix_changelog.md](./08_appendix_changelog.md) |
| 11 | 변경 이력 | [08_appendix_changelog.md](./08_appendix_changelog.md) |
| Q | Round 1 답변 정리 (ARCHIVE — §9.3로 추적 일원화) | [01_questions_round1.md](./01_questions_round1.md) |

---

## Cross-reference 규칙

- 외부 문서(`docs/design/`, `docs/tasks/`, `CLAUDE.md`)에서 PRD를 참조할 때는 **절 번호만** 사용 (예: `PRD §4.2`, `PRD §9.3 #5`)
- 절 번호는 본 분리에도 변하지 않음 — 외부 참조 안전
- 파일 경로 직접 참조는 본 인덱스(`docs/prd/00_index.md`)로 통일

## 자주 갱신되는 절 (PR diff 집중 영역)

| 절 | 갱신 주기 | 이유 |
|---|---|---|
| §9.3 외부 의사결정 의존 항목 | round 2/3 답변 시마다 | KSPO 외부 부서 확정 시 1~2개씩 해소 |
| §11 변경 이력 | PR마다 1줄 추가 | 모든 PRD 변경의 단일 추적 |
| §1.4 KPI 권장 목표 | 운영 1개월 후 | 측정값 기반 합의·조정 |

→ 이 3개 절이 자주 변경되므로, PRD 분리의 가장 큰 이득은 다른 절(§1~§8)이 안정 영역으로 분리되는 것.

## 빠른 참조

- 사업 담당자: §1, §2, §3 → [02_overview.md](./02_overview.md), [03_stakeholders_scope.md](./03_stakeholders_scope.md)
- IT/보안: §5, §6 → [05_nfr_infra.md](./05_nfr_infra.md)
- 사업관리/PMO: §7, §8, §9 → [06_cost_schedule.md](./06_cost_schedule.md), [07_risks_open.md](./07_risks_open.md)
