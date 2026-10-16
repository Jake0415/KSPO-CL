# KSPO 인수 체크리스트

> 본 체크리스트는 무한아이티 → KSPO 인계 시점에 1회 확인 후 양측 서명.

## 1. 시스템 가동

- [ ] `curl http://localhost/readyz` 응답에 6 항목 모두 정상
  - `db: ok`, `redis: ok|stub`, `qdrant_dim: 3072`, `qdrant_mode`, `proxy_configured`, `monthly_cost_krw`
- [ ] `docker compose ps` 7개 서비스 모두 `healthy` 또는 `Up`
- [ ] CI badge 녹색 (GitHub Actions, 단위 테스트 통과)
- [ ] worker 로그 `event=cron_registered cron_count=3` 1회 출력 확인

## 2. 데이터·콘텐츠

- [ ] 파일럿 도메인 1개(KSPO 본사이트) 적재 커버리지 ≥ 80%
- [ ] `chunks.kb_status='OK'` 비율 ≥ 95%:
  ```sql
  SELECT COUNT(*) FILTER (WHERE kb_status='OK')::float / COUNT(*) FROM chunks;
  ```
- [ ] `llm_usage` 월 누계가 한도 이내:
  ```bash
  python scripts/kpi_measure.py
  ```
- [ ] Qdrant 컬렉션 차원 검증: `curl http://qdrant:6333/collections/{idx} | jq .result.config.params.vectors.size` → 3072

## 3. 운영 절차

- [ ] Admin 1명에게 본 매뉴얼 + UI 시연 완료 (예: 도메인 등록·incremental·force refresh·삭제)
- [ ] KSPO IT에 정기 재시작 윈도우 + 보안 패치 SOP 전달
- [ ] OpenAI 카드 결제 실패 SOP ([런북 B.2.B](../runbook/B_openai_failure.md)) 회계팀 공유
- [ ] SMTP 알림 테스트 — 임시로 한도를 낮춰 80% 도달 → 메일 1회 수신 확인 → 한도 복원

## 4. 보안

- [ ] `.env`는 git/공유 채널에 미포함 — 운영 호스트에서만 관리
- [ ] `ADMIN_PASSWORD_BCRYPT` 운영 호스트에서 신규 생성 (개발 더미 미사용)
- [ ] `SESSION_SECRET` 운영 호스트에서 32바이트 랜덤 신규 생성
- [ ] `OPENAI_API_KEY` 분기 회전 SOP 확립
- [ ] TLS 인증서 만료일 1개월 전 리마인더 등록 (KSPO IT)

## 5. 문서

- [ ] 운영 매뉴얼 PDF (`dist/kspo-ingest_운영매뉴얼_v2.1.pdf`) — KSPO Admin·IT 양쪽 수령
- [ ] 교육 슬라이드 PDF — 1회 진행 + 녹화(가능 시)
- [ ] `docs/runbook/A,B,C` PDF 별쇄 (별도 빌드 가능)
- [ ] `docs/runbook/deploy.md` PDF — 신규 환경 구축 시 참조

## 6. 외부 의사결정 잔존 항목 (PRD §9.3)

- [ ] **#2 KPI 권장 목표** — 운영 1개월 측정값으로 합의
- [ ] **#9 파일럿 기간/도메인** — KSPO 합의 후 본 매뉴얼에 명시
- [ ] **PoC P1~P4** — 정식 운영 전환 직전 재검증 일정 합의

## 7. 사후 지원

- [ ] 무한아이티 6개월 버그 지원 기간 시작일 합의 (서면)
- [ ] 무한아이티 연락처 + 응답 SLA(영업일 24h 등) 명시
- [ ] 인계 종료 후 1개월 시점에 KSPO Admin·IT 인터뷰 1회 — 운영 안정성 확인

## 8. 인계 완료 서명

| 역할 | 이름 | 서명 | 일자 |
|---|---|---|---|
| 무한아이티 PM | | | |
| KSPO 사업관리 | | | |
| KSPO IT | | | |
| KSPO Admin | | | |
