# PRD §9 — 위험 · 가정 · 외부 의사결정 의존 항목

> 본 파일: PRD **§9**. 전체 인덱스: [00_index.md](./00_index.md)
> 작성: 2026-05-07 / 상태: draft v1.4
> ⚠ **갱신 빈도 높음** — Round 2/3 답변 시마다 §9.3 표가 변경됨. PR diff 집중 영역.

---

## 9. 위험 · 가정 · 미해결 항목

### 9.1 가정 (assumption)

- KSPO 본사이트·패밀리 사이트 콘텐츠는 **모두 공개 자료** (로그인 없는 페이지만 크롤) ✓
- OpenAI API는 사내 프록시 경유로 outbound 가능 ✓
- 단일 Admin 운영자 모델이 공공기관 정보보호 가이드상 허용 ✓
- 백업 미운영 정책 (재크롤 복원)이 KSPO 내부 정책상 허용 — **재확인 필요**

### 9.2 위험

| 위험 | 영향 | 완화 |
|---|---|---|
| OpenAI 가격 변동 → 월 15만원 초과 | 호출 자연 정지 | 알림 + 카드사 차단으로 자연 종료 |
| Trafilatura가 KSPO 게시판 본문을 못 잡음 | 검색 품질 저하 | Tier 2에서 `crawl_rules`(detail 셀렉터) 추가 |
| HWP 첨부 비율 높음 → 검색에 안 잡힘 | 검색 품질 저하 | 운영 측정 후 Tier 2로 HWP 추출 도입 검토 |
| Tiledesk 컬렉션 payload 컨벤션이 가정과 다름 | 적재 후 검색 안 됨 | PoC P1·P4에서 사전 검증 |
| 단일 Admin 계정 분실 | UI 접근 불가 | 호스트 권한자 `.env` 수정 SOP |

### 9.3 외부 의사결정 의존 항목 (PRD 잠정안 + 외부 확정 필요)

본 PRD가 잠정 결정을 명시했으나, KSPO 외부 부서·일정에 따라 최종 확정되는 항목:

| # | 항목 | PRD 잠정안 | 결정 주체 | 결정 시점 |
|---|---|---|---|---|
| 1 | 프록시 host:port 실값 | `.env`에 placeholder | KSPO 인프라팀 | 운영 시작 시 |
| 2 | KPI 권장 목표 수치 | §1.4 후보값 (90/95/7일 등) | KSPO + 무한아이티 | 운영 1개월 내 |
| 3 | 백업 미운영 정책 허용 | 미운영 (재크롤 복원). Fallback SOP 준비됨 | KSPO IT | 운영 시작 전 |
| 4 | 호스트 도입 방식 | 기존 활용 권장, 미충족 시 신규 VM | KSPO IT 자산팀 | M0 시작 전 |
| 5 | TLS 종료 위치 | nginx 컨테이너 종료 | KSPO IT 보안 | M0.T0.2 진입 전 |
| 6 | 이미지 레지스트리 | 사내 우선, 미보유 시 로컬 빌드 | KSPO IT | M0.T0.2 진입 전 |
| 7 | CSAP/ISMS-P 대상 여부 | 비대상 가정 | KSPO IT 보안 | 점검 시점 |
| 8 | 개발 deadline | 추정 3~4주 | KSPO 사업관리 | PRD 승인 시 |
| 9 | 파일럿 기간·도메인 | 2~4주·KSPO 본사이트 1개 | KSPO + 무한아이티 | M5 종료 시점 |
| 10 | KSPO 기존 FAQ 메뉴 유지 여부 | 챗봇 도입 후에도 별도 유지 (§1.3) | KSPO 운영기획 | 챗봇 개통 전 |

> 위 항목들은 **PRD 본문이 결정한 내용을 외부 부서가 확인·확정만 하면 되는 형태**다. 잠정안 거절 시 본 PRD 차기 버전(v2)에서 갱신.

### 9.4 별도 진행 항목 (PRD 외부)

- **카드 한도 소진 시 운영 절차 보강** — 런북 B.2.B로 이미 작성 완료 (`docs/design/_appendix.md` §B.2)
- **M0.T0.4 frontend bootstrap Task 명세** — 별도 작업 (PRD 승인 후) ← 완료 (`docs/tasks/M0_T0_4.md`)
- **design docs 동기화** — `docs/design/05_devops_ops.md` §5.1 docker compose, §5.2 Tiledesk 접근, `01_architecture.md` 토폴로지를 본 PRD §6.3과 일치시키는 작업 (별도 commit)

---

이전: [§7 비용·§8 일정](./06_cost_schedule.md) · 다음: [§10 참조·§11 변경이력](./08_appendix_changelog.md)
