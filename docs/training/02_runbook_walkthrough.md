---
marp: true
theme: default
paginate: true
header: "kspo-ingest 인계 교육 — 런북 시연"
---

# 운영 런북 시연

A: KB 차원 mismatch · B: OpenAI 실패 · C: Tiledesk 다운

---

## 분기 결정 트리

```
사고 발생
   │
   ├─ /readyz qdrant_dim != 3072  → 런북 A
   ├─ Job error_message에 'openai' / '429' / '401'  → 런북 B
   ├─ Tiledesk 챗봇이 우리 데이터 못 찾음  → 런북 C
   └─ 그 외  → docs/operations/03_troubleshooting.md
```

---

## 런북 A — KB 차원 mismatch

**증상**:
- `/readyz` 응답 `qdrant_dim != 3072` 또는 `0`
- HTTP 503

**원인**:
- 임베딩 모델 변경 (예: 3-large → 3-small)
- Tiledesk 측이 다른 차원으로 컬렉션 생성

**조치**:
1. 임시: 새 컬렉션 생성 (`QDRANT_INDEX_NAME` 변경)
2. 장기: 무한아이티에 보고 + 재크롤 일정 협의

---

## 런북 B.1 — OpenAI 일시 장애

**증상**:
- Job ERROR + `error_message: "openai 5xx"` 또는 `timeout`

**조치**:
- 자동 재시도 — tenacity가 5회 시도
- 5회 모두 실패 → ERROR 페이지로 표시
- 다음 incremental에서 재시도

→ **방치하면 자동 회복**

---

## 런북 B.2.A — OpenAI 인증 실패 (401)

**증상**: 모든 Job 즉시 ERROR + `401 invalid_api_key`

**조치**:
1. KSPO IT에 즉시 보고 (회계 연락 필요할 수도)
2. OpenAI 콘솔에서 키 활성 확인
3. 새 키 발급 → `.env` `OPENAI_API_KEY` 교체
4. `docker compose up -d --force-recreate api worker`
5. ERROR Job 재실행: `POST /api/jobs/incremental/{id}`

---

## 런북 B.2.B — 카드 한도 소진 (429)

**증상**: Job ERROR + `insufficient_quota` 또는 매월 1일 갑작스런 다수 ERROR

**조치**:
1. **즉시**: 80% 알림 메일 받았는지 메일함 확인
2. KSPO 회계팀에 결제 보고
3. 결제 재개 후 5~10분 대기 (OpenAI 측 반영)
4. 새 Job 트리거 → SUCCESS 확인

---

## 런북 C — Tiledesk 다운

**증상**:
- Tiledesk 챗봇 자체가 응답 없음
- 본 시스템은 정상 (KB 적재 OK)

**우리 측 조치**:
- 본 시스템 Qdrant 컬렉션 보존 — Tiledesk 복구 후 자동 재연결
- 외부 모드(`KB_BOOTSTRAP=external`)면 우리 시스템 영향 거의 없음
- KSPO IT가 Tiledesk 측 SLA 따라 대응

---

## 알림 메일 — SMTP 설정 확인

월 80% 알림이 안 옵니다? →

```bash
docker compose exec api python -c "
import asyncio
from kspo_ingest.observability.email import send_alert_email
asyncio.run(send_alert_email(subject='test', body='test'))
"
```

True 응답 + 메일함 수신 확인. False면 `.env` `SMTP_*` 점검.

---

## 실습 2 (15분)

1. OpenAI 키를 잘못된 값으로 교체 → Job 트리거 → 401 확인
2. 키 복구 → 재시도 → SUCCESS
3. 한도를 0으로 → /readyz 응답 확인
4. 한도 복구

---

## 다음

`03_qna.md` — 자주 묻는 질문 20선
