# 인계·외부 의사결정 추적

본 디렉터리는 KSPO 외부 부서·이해관계자와의 의사결정 흐름을 추적한다.

## 파일

| 파일 | 용도 |
|---|---|
| `kspo_questions_v1.md` | PRD §9.3 10건을 부서별 송부용으로 재구성한 1차 질의서 |
| `kspo_questions_v2.md` 등 | 1차 회신 후 잔존 항목 또는 추가 질문 (필요 시 작성) |
| `responses/` | 부서별 회신 원본 보관 (`<부서>_<YYYYMMDD>.md`) |
| `decisions_log.md` | 확정된 결정의 단일 진실원 (날짜·결정자·근거) — 향후 작성 |

## 흐름

```
PRD §9.3 표 ─→ kspo_questions_v1.md 송부
                     ↓
              부서별 회신 (responses/)
                     ↓
              decisions_log.md 등재
                     ↓
              PRD §9.3 행 제거 + §11 changelog 갱신
```

## 단일 진실원 정책

- **확정 전**: PRD §9.3 표가 진실원 (잠정안 + 결정 시점)
- **확정 후**: PRD 본문(§5.1, §6.1, §7.1 등) + decisions_log.md
- 본 `handover/` 자료는 **추적 기록**일 뿐, 코드·운영 의사결정은 PRD를 본다
