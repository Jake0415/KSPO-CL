# 배포 런북 — kspo-ingest

> 본 문서는 **사고 대응**이 아닌 **계획된 배포·업데이트·롤백** 절차다.
> 사고 시나리오는 동일 디렉터리의 `A_kb_dim_mismatch.md` / `B_openai_failure.md` / `C_tiledesk_down.md` 참조.
>
> 설계 배경(왜 이렇게 구성했는지)은 `docs/design/05_devops_ops.md` 참조.

---

## 0. 본 런북이 다루는 범위

| 시나리오 | 대상 절차 |
|---|---|
| 첫 배포 (clean install) | §3 |
| 코드 업데이트 (main 갱신 후 재배포) | §4 |
| 환경변수 변경 | §5 |
| 마이그레이션 적용 | §6 |
| 롤백 (직전 정상 상태로) | §7 |
| Qdrant 모드 전환 (self_hosted ↔ external) | §8 |

---

## 1. 사전 조건

### 1.1 호스트 사양 (최소)

| 항목 | 권장 |
|---|---|
| OS | Ubuntu 22.04 LTS / RHEL 8 / Debian 12 |
| CPU | 4 vCore |
| RAM | 8 GB (qdrant self-hosted 포함 시 12 GB) |
| Disk | 50 GB SSD (`storage/`, `pgdata/`, `qdrant_data/` 합계) |
| Outbound | `api.openai.com:443`, `cdn.jsdelivr.net:443`(Pretendard), KSPO 사이트 |

### 1.2 설치 의존성

```bash
# Docker Engine + Compose v2 (한 번만)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
# 새 셸에서 docker compose version 확인
```

### 1.3 GitHub 접근

private repo이므로 deploy key 또는 PAT 필요:

```bash
# 옵션 A: deploy key (권장)
ssh-keygen -t ed25519 -f ~/.ssh/kspo_deploy -N ""
# 공개키를 GitHub repo Settings → Deploy keys에 read-only 등록

# 옵션 B: PAT
git clone https://oauth2:${GITHUB_TOKEN}@github.com/Jake0415/kspo-ingest.git
```

---

## 2. `.env` 작성

### 2.1 템플릿 복사

```bash
cd kspo-ingest
cp .env.example .env
chmod 600 .env
```

### 2.2 시크릿 생성

```bash
# ADMIN_PASSWORD_BCRYPT — 운영 호스트에서 직접 생성, 평문 비밀번호는 어디에도 저장 금지
docker run --rm python:3.12-alpine sh -c \
  'pip install -q passlib[bcrypt] && python -c "from passlib.hash import bcrypt; import getpass; print(bcrypt.using(rounds=12).hash(getpass.getpass(\"new password: \")))"'

# SESSION_SECRET — 32 bytes 랜덤
openssl rand -hex 32

# POSTGRES_PASSWORD — 32 chars 랜덤
openssl rand -base64 24 | tr -d '/+=' | head -c 32; echo
```

### 2.3 채워야 하는 키 (요약)

| 키 | 비고 |
|---|---|
| `ADMIN_USERNAME`, `ADMIN_PASSWORD_BCRYPT` | §2.2로 생성 |
| `SESSION_SECRET` | §2.2로 생성, 32바이트 |
| `POSTGRES_PASSWORD` | §2.2로 생성 |
| `OPENAI_API_KEY` | KSPO 발급 키 |
| `QDRANT_URL` | 자체 컨테이너: `http://qdrant:6333` / 외부: KSPO·Tiledesk 제공값 |
| `QDRANT_API_KEY` | 외부 모드에서만 |
| `QDRANT_INDEX_NAME` | 외부: Tiledesk 측 컬렉션명 / 자체: `kspo_dev` 등 |
| `KB_BOOTSTRAP` | `managed`(자체) / `external`(Tiledesk) |
| `HTTPS_PROXY`, `NO_PROXY` | KSPO 사내망 진입 시 |

> ⚠️ `.env`는 절대 git/공유 채널에 올리지 않는다. 분실 시 §2.2를 다시 돌려 재발급 — 세션은 모두 만료된다.

---

## 3. 첫 배포 (clean install)

```bash
# 1. 코드 받기
git clone git@github.com:Jake0415/kspo-ingest.git
cd kspo-ingest
git checkout main         # 또는 특정 태그 (예: v0.3.0)

# 2. .env 작성 (§2)

# 3. 이미지 빌드 + 컨테이너 기동 (web/api/worker 빌드 ~ 5~10분)
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d nginx web api worker postgres redis qdrant

# 4. DB 마이그레이션 (1회)
docker compose -f docker/docker-compose.yml --profile migrations run --rm migrations

# 5. 헬스 체크 (§9 참조)
curl -fsS http://localhost/readyz | jq .
```

**기대 결과**: `db: ok`, `qdrant_dim: 3072`, `qdrant_mode: self_hosted`(또는 `external`), HTTP 200.

---

## 4. 업데이트 배포 (코드 갱신)

```bash
cd kspo-ingest
git fetch origin
git log HEAD..origin/main --oneline       # 어떤 변경이 들어오는지 확인
git pull --ff-only origin main

# 변경 영역에 따라 빌드 대상 선택
docker compose -f docker/docker-compose.yml build api worker     # Python 변경
docker compose -f docker/docker-compose.yml build web            # web/ 변경
# 둘 다 영향 시 그냥 `docker compose ... build`

# 마이그레이션 신규면 §6 먼저 실행
docker compose -f docker/docker-compose.yml up -d --no-deps api worker web

# 검증
curl -fsS http://localhost/readyz | jq .
docker compose -f docker/docker-compose.yml logs --tail=50 api worker
```

> nginx/postgres/redis는 일반적으로 재시작 불필요.

---

## 5. 환경변수 변경

`.env`만 수정한 경우:

```bash
# api/worker는 .env를 startup에서 읽으므로 재시작 필요
docker compose -f docker/docker-compose.yml up -d --force-recreate --no-deps api worker
```

`SESSION_SECRET` 교체 시 모든 세션이 무효화되어 사용자 재로그인이 필요하다.

`OPENAI_API_KEY` 교체 시 진행 중인 임베딩 Job은 다음 재시도에서 새 키로 동작.

---

## 6. 마이그레이션 적용

```bash
# 사전: 새 revision이 있는지 확인
git log --diff-filter=A --name-only -- migrations/versions | head -10

# 적용 (멱등 — 이미 head면 no-op)
docker compose -f docker/docker-compose.yml --profile migrations run --rm migrations

# 검증 — 현재 head revision
docker compose -f docker/docker-compose.yml --profile migrations run --rm migrations alembic current
```

> downgrade는 자동화하지 않는다 — 데이터 손실 가능. 필요 시 백업 후 수동 `alembic downgrade <rev>`.

---

## 7. 롤백

### 7.1 코드 롤백 (마이그레이션 영향 없음)

```bash
git log --oneline -10                    # 직전 정상 commit hash 확인
git checkout <prev_sha>
docker compose -f docker/docker-compose.yml build api worker web
docker compose -f docker/docker-compose.yml up -d --no-deps api worker web
```

### 7.2 마이그레이션을 포함한 롤백

신중하게 — 데이터 손실 위험.

```bash
# 1. 현재 head 확인
docker compose --profile migrations run --rm migrations alembic current

# 2. PG 백업 (복원 보험)
docker compose exec postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > /tmp/before-rollback.sql

# 3. 코드 체크아웃 (이전 sha)
git checkout <prev_sha>

# 4. 마이그레이션 다운그레이드 — 이전 sha의 head로
docker compose --profile migrations run --rm migrations \
  alembic downgrade <target_revision>

# 5. 컨테이너 재기동
docker compose up -d --no-deps api worker web
```

본 시스템은 백업 인프라를 운영하지 않으므로(설계 결정), `pg_dump` 보험을 매 배포 직전에 권장.

---

## 8. Qdrant 모드 전환 (self_hosted → Tiledesk external)

PRD §4.2 절차:

```bash
# 사전: PoC P1~P4 재검증 의무
# (Tiledesk 컬렉션 차원 / payload 컨벤션 / tag prefix 호환 / search latency)

# 1. .env 수정
sed -i.bak \
    -e 's|^QDRANT_URL=.*|QDRANT_URL=https://tiledesk.kspo.example|' \
    -e 's|^QDRANT_API_KEY=.*|QDRANT_API_KEY=...|' \
    -e 's|^QDRANT_INDEX_NAME=.*|QDRANT_INDEX_NAME=tilellm|' \
    -e 's|^KB_BOOTSTRAP=.*|KB_BOOTSTRAP=external|' \
    .env

# 2. api·worker 재시작
docker compose up -d --force-recreate --no-deps api worker

# 3. 헬스 체크 — qdrant_mode=external 확인
curl -fsS http://localhost/readyz | jq .

# 4. 자체 qdrant 컨테이너·볼륨 정리 (선택, 데이터 손실 비가역)
docker compose stop qdrant
docker compose rm -f qdrant
docker volume rm kspo-ingest_qdrant_data

# 5. 전체 재인덱싱 — 모든 도메인에 full Job
# Admin UI에서 도메인별 "전체 재인덱싱" 또는:
# curl -u admin:... -X POST http://localhost/api/jobs/full -d '{"domain_id": 1}'
```

---

## 9. 헬스 체크

| 엔드포인트 | 정상 응답 |
|---|---|
| `GET /healthz` | `{"status":"ok"}` 200 |
| `GET /readyz` | `{"db":"ok","redis":"...","qdrant_dim":3072,"qdrant_mode":"...","proxy_configured":bool}` 200 |
| `GET /api/auth/me` (Basic Auth) | `{"username":"admin","via":"basic"}` 200 |
| 웹 / | HTML 200, 로그인 페이지 |

`/readyz`가 503 반환 시 어떤 키가 fail인지 보고 해당 런북으로 이동 (qdrant 관련은 A, OpenAI 관련은 B).

---

## 10. 운영 일과 (간단)

| 주기 | 동작 |
|---|---|
| 매 배포 직전 | `pg_dump` 보험 (§7.2 step 2) |
| 매주 | `docker system prune -f` (이미지 캐시 정리), `docker compose logs api worker | grep -E "ERROR|WARN" | tail -100` |
| 월 1회 | 누적 비용 확인 — Admin UI 또는 `SELECT sum(cost_krw) FROM llm_usage WHERE used_at >= now() - interval '30 days'` |
| 분기 1회 | OpenAI 임베딩 모델 가격 변경 여부 확인 → `src/kspo_ingest/embed/cost.py` 갱신 |

---

## 11. 흔한 실패 → 분기

| 증상 | 다음 단계 |
|---|---|
| `/readyz` qdrant 관련 fail | 런북 A |
| Job FAILED + log에 `openai` / `429` / `401` | 런북 B |
| Tiledesk 외부 모드 + 응답 없음 | 런북 C |
| 컨테이너 시작 실패 | `docker compose logs <service>` → 이미지 재빌드 또는 `.env` 점검 |
| `pip install -e .` 빌드 실패 | `README.md`가 컨텍스트에 포함됐는지 확인 (Dockerfile.api/worker/migrations §3) |
| Next.js 빌드 OOM | 빌드 머신 RAM 4GB 이상 권장 |

---

## 12. 명령 치트시트

```bash
# 상태
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs --tail=200 -f api worker

# 단일 서비스 재시작
docker compose -f docker/docker-compose.yml restart api

# 셸 진입
docker compose -f docker/docker-compose.yml exec api bash
docker compose -f docker/docker-compose.yml exec postgres psql -U "$POSTGRES_USER" "$POSTGRES_DB"

# 정지 (볼륨 보존)
docker compose -f docker/docker-compose.yml down

# 정지 + 볼륨 삭제 (⚠️ 비가역)
docker compose -f docker/docker-compose.yml down -v
```
