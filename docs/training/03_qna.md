---
marp: true
theme: default
paginate: true
header: "kspo-ingest 인계 교육 — Q&A"
---

# 자주 묻는 질문 20선

KSPO Admin·IT가 인계 후 가장 많이 묻는 항목

---

## Q1. 본 시스템과 Tiledesk-LLM의 경계?

- **kspo-ingest**: 크롤·정제·청킹·임베딩 → Qdrant **적재**까지
- **Tiledesk-LLM**: 같은 Qdrant를 **검색** + LLM 답변 생성
- 우리는 `/api/ingestion`을 호출하지 않는다(절대 금지) — Direct 모드

---

## Q2. 도메인 추가하면 언제 챗봇이 인지?

1. 도메인 등록 + full Job 시작
2. 1~3시간 후 INDEXED (사이트 규모 따라 다름)
3. **즉시** Tiledesk 챗봇이 검색 가능 (Tiledesk-LLM이 같은 Qdrant 읽음)

---

## Q3. 첨부 파일도 챗봇이 답변에 사용?

- v2.0 Lite: **메타만** 적재 (URL/파일명/MIME)
- 챗봇은 답변에 "관련 자료: [링크]" 형식으로 노출
- `GET /files/{id}` → 302 redirect로 KSPO 사이트 직접 다운로드 유도

본문 추출/임베딩은 운영 후 품질 부족 시 Tier 2로 도입 검토.

---

## Q4. 비용이 갑자기 늘어나면?

1. 80% 도달 시 SMTP 알림 자동 발신 (1개월 1회)
2. `python scripts/kpi_measure.py` 즉시 누계 확인
3. `v_cost_daily` 뷰 → 어느 날부터 급증인지 추적
4. 원인: incremental에서 hash skip이 안 됨? — 사이트 본문 변경 다수?

---

## Q5. 검색 결과가 이상하다 (Tiledesk 측)

→ `docs/operations/03_troubleshooting.md` Q4 참조.

- 청크 token 분포 점검
- summary 채워졌는지 점검
- 해당 페이지 직접 force refresh 후 재테스트

---

## Q6. 동적 페이지(JS 렌더링)는?

v2.1 미지원. Trafilatura가 빈 본문 인식 → DROPPED `too_short`

→ 운영 측정 후 도입 검토 (Tier 2 — Playwright)

---

## Q7. PII 노출 발견 시?

1. 즉시 `deny_patterns`에 추가 (해당 URL 더는 안 들어옴)
2. 이미 적재된 페이지 — 도메인 비활성화→재활성화는 무거움
3. SQL DELETE는 KSPO IT 협의 후만

---

## Q8. 정기 재시작 윈도우와 weekly cron 충돌?

- 재시작: 매월 둘째 일요일 02:00
- weekly cron: 매주 일요일 03:00
- **02:30 이전 재시작 종료 권장** — 30분 buffer

---

## Q9. 비밀번호 분실 시?

`docs/operations/03_troubleshooting.md` Q8 참조.

- bcrypt 해시 새로 생성 → `.env` 교체 → api 재시작
- 분실 자체는 보안 사고로 보고

---

## Q10. 무한아이티 지원 기간?

- **6개월 버그 지원** (서면 합의)
- 응답 SLA: 영업일 24시간
- 6개월 후 추가 지원은 별도 계약

---

## Q11. 의존성 업그레이드 주기?

- KSPO IT 분기 1회 점검
- security advisory 발견 시 즉시 패치
- `uv pip list --outdated` + Dependabot 알림

---

## Q12. Qdrant 자체 모드 → Tiledesk 외부 전환은 언제?

PRD §4.2 — **PoC P1~P4 재검증** 완료 후 KSPO 합의로 결정.

전환 시 [docs/runbook/deploy.md §8](../runbook/deploy.md) 절차.

---

## Q13. 백업이 없는 이유?

설계 결정 (CLAUDE.md): "백업 미운영. 손실 시 재크롤·재정제·재임베딩으로 복원"

근거:
- 원본 콘텐츠는 KSPO 사이트가 단일 진실원
- 임베딩 비용은 월 한도 내 충분히 재실행 가능
- 백업 인프라 비용 > 재크롤 비용

---

## Q14. 재크롤에 얼마나 걸리나?

- 1 도메인 1000 페이지 기준 ~1시간 (rate_limit 1.5 RPS)
- 모든 도메인 동시 재크롤 — 도메인 수 × 1시간
- M4.T4.4 frontier 도입 시 단축 가능

---

## Q15. 신규 도메인이 KSPO 본사이트와 다른 인코딩?

- charset-normalizer가 자동 감지 (UTF-8/EUC-KR/CP949 등)
- 인코딩 실패 → DROPPED `encoding_error`
- 운영 중 발견 시 KSPO IT 보고

---

## Q16. /readyz 503이 잠깐씩 나는 이유?

- DB 연결 일시 끊김 (PG 재시작 등)
- 30초 내 자동 회복 정상
- 5분 이상 지속 시 사고

---

## Q17. cron이 동작 안 했어요

```bash
docker compose exec worker arq --check kspo_ingest.tasks.worker.WorkerSettings
```

- worker 컨테이너 정상 가동 중인지
- 컨테이너 시간이 KST인지 (`docker compose exec worker date`)

---

## Q18. 새 직원에게 인계?

- 본 슬라이드 4세트 + 매뉴얼 PDF 1세트
- Admin UI 시연 30분
- 런북 시연 30분
- 1주일 shadow 운영 권장

---

## Q19. 무한아이티 연락처?

(기재) 영업일 9:00~18:00 응답 / 응급 시 24h 메신저 (별도 채널)

---

## Q20. 뭘 더 물어봐야 할지 모르겠습니다

1. `docs/operations/00_overview.md`부터 다시 읽기
2. `docs/runbook/A,B,C` 1회 통독
3. 인계 1개월 후 인터뷰 — 무한아이티가 회수

---

## 감사합니다

질문 받습니다.

연락처: (기재)
