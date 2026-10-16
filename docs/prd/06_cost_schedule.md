# PRD §7 — 비용 · §8 — 일정 · 롤아웃

> 본 파일: PRD **§7 + §8**. 전체 인덱스: [00_index.md](./00_index.md)
> 작성: 2026-05-07 / 상태: draft v1.4

---

## 7. 비용

### 7.1 OpenAI 사용료

| 항목 | 결정 |
|---|---|
| **월 한도** | 150,000원 (≈ USD $110, 환율 1370원 기준) ✓ |
| 결제 수단 | 별도 카드 등록·관리 ✓ |
| **임계 단위** | 월누계만 관리 (일 임계 없음) ✓ |
| **한도 도달 시** | (a) 알림만, 호출은 계속. 카드사 차단 시점에서 OpenAI HTTP 429 `insufficient_quota` 응답 → ARQ 백오프로 자연 정지. 회복은 [런북 B.2.B](../design/_appendix.md#b2b-카드-한도-소진결제-실패-http-429-insufficient_quota) 절차 ✓ |
| **사전 알림** | 월 누계 80% 도달 시 이메일 + UI 배너 (`05_devops_ops.md` §5.7) ✓ |
| 가격 갱신 | 자동 회수는 Tier 2. 현 단계는 하드코딩 또는 수동 PR ✓ |

### 7.2 인프라 비용

- **사내 IDC 사용** — 본 PRD 범위 내 별도 인프라 비용 산정 없음 (호스트는 KSPO 자산)
- **신규 호스트 도입 시**: KSPO 자산 예산으로 별도 산정 (본 PRD 범위 외)
- **사후 지원 기간 외 비용**: M5 인수 후 무한아이티 6개월 버그 지원 종료 시점부터 KSPO 자체 부담 (인력 비용은 KSPO 내부)

---

## 8. 일정 · 롤아웃

### 8.1 마일스톤

| M | 내용 | Task 수 |
|---|---|---|
| M0 | 부트스트랩 (Docker, Alembic, /healthz·/readyz, CI, frontend bootstrap) | 4~5 |
| M1 | 데이터 모델(6 테이블) + Admin 골격 + 도메인 CRUD | 4~5 |
| M2 | Crawl + Clean + Refine 파이프라인 | 4 |
| M3 | Chunk + Embed + Qdrant Direct + 첨부 | 3~4 |
| M4 | Incremental + Manual Refresh + 주간 cron | 2~3 |
| M5 | 운영 (로깅·테스트·문서·런북) + 인수 | 3~4 |

> 총 20~25 Task. **개발 기간**: PRD 승인 후 **3~4주** (docx §0.4 v2.0 Lite 추정치 기준).
>
> **시작·종료 deadline**: KSPO 사업관리 의사결정 사항. 본 PRD에서는 추정값만 명시 — PRD 승인 시 별도 일정표로 확정.

### 8.2 롤아웃 단계

```
1. PoC (P1~P4)             — Tiledesk Qdrant (가용 시; 미가용 시 정식 전환 시점에 재검증으로 연기)
2. 본 개발 (M0~M5)         — 자체 Qdrant
3. 파일럿 운영              — 자체 Qdrant
4. 정식 운영 진입            — Tiledesk Qdrant로 전환 (PoC P1~P4 재검증 의무)
5. KSPO 인수                — M5 종료 직후, 무한아이티 6개월 버그 지원
6. Tiledesk 챗봇 도입         — 본 시스템 완료 후
```

> **PoC 대상**: P1~P4는 Tiledesk Qdrant 호환성 검증(payload 키, 차원, upsert/delete, e2e 검색)이 목적이므로 자체 Qdrant로 검증하지 않는다. Tiledesk Compose가 가용한 시점에 1~2일 단기 실행. 미가용 시 4단계(정식 전환) 직전에 의무적으로 재검증한다 (`docs/tasks/00_roadmap.md` §3.1 참조).

> **파일럿 잠정 계획**:
> - **기간**: 2~4주
> - **대상 도메인**: KSPO 본사이트(`www.kspo.or.kr`) 1개로 시작 — 패밀리 사이트는 파일럿 종료 후 단계 추가
> - **측정 항목**: 적재 커버리지 · Job 성공률 · 월 LLM 비용 추세 · 검색 품질(Tiledesk 측 협조 — Tiledesk 도입 후)
> - **종료 조건**: KPI 권장 목표 달성 + 운영 매뉴얼 확정 + KSPO Admin 인계 교육 완료
> - 정확한 기간·도메인은 M5 종료 시점 KSPO와 합의로 조정

### 8.3 인계 산출물

- 코드 + Docker Compose + `docs/`
- 운영 매뉴얼 — **PDF 책자** + **프레젠테이션 교육 1회** ✓
- 런북 3종 (KB 차원 mismatch / OpenAI 인증 실패 / Tiledesk 다운) + **카드 한도 소진 보강 (TBD)**

---

이전: [§5 NFR·§6 인프라](./05_nfr_infra.md) · 다음: [§9 위험·미해결](./07_risks_open.md)
