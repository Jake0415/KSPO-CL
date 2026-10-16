# 보고서 작성 가이드

본 디렉터리는 KSPO 측에 제출하는 보고서 템플릿·작성본을 보관한다.

## 파일럿 보고서

- **템플릿**: [pilot_template.md](pilot_template.md)
- **작성 시점**: 파일럿 종료 시 (PRD §8.2 step 3 → 4 진입 직전)
- **저장 형식**: `pilot_<YYYYMMDD>.md` (시작일 또는 종료일 기준)
- **데이터 소스**:
  - `python scripts/kpi_measure.py --json` (현재 시점 측정)
  - `GET /api/kpi/latest` / `GET /api/kpi/history?days=30` (스냅샷 누적)
  - PG 직접 조회: `SELECT * FROM v_stats_overview;` `SELECT * FROM v_cost_daily;`

## 월간 운영 보고서 (인수 후)

- KSPO 자체 작성. 형식 자유. 본 디렉터리에 `monthly_<YYYYMM>.md`로 저장 권장.
- 권장 항목: KPI 4종 측정값, 발생 이슈, 비용 분석, 다음 달 계획.

## 인계 회의 의사록

- M5 종료 시점 1회 작성. `handover_<YYYYMMDD>.md`.
- 참석자: 무한아이티 PM + KSPO 사업관리 + KSPO IT + KSPO Admin.
- 결정 사항·합의 사항·미정 사항 분리 기록.

## 사후 인터뷰 (1개월 후)

- 무한아이티가 KSPO Admin·IT 인터뷰 후 보고. `post_handover_interview_<YYYYMMDD>.md`.
- 운영 안정성 / 미해결 이슈 / 추가 개선 요청 정리.
