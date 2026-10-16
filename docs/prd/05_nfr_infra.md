# PRD §5 — 비기능 요구사항 (NFR) · §6 — 인프라

> 본 파일: PRD **§5 + §6**. 전체 인덱스: [00_index.md](./00_index.md)
> 작성: 2026-05-07 / 상태: draft v1.4

---

## 5. 비기능 요구사항 (NFR)

### 5.1 가용성

- **목표 가용률**: 업무시간(평일 09:00~18:00) 기준 **99.0%** (월 약 1.5시간 다운 허용)
- **24/7 가용 목표 아님** — 외부 챗봇 트래픽 가용성은 Tiledesk 측 책임
- **정기 재시작 윈도우**: 매월 둘째 일요일 02:00 KST (잠정). KSPO IT 보안 패치·재시작 일정에 동기화
- **계획된 다운타임**: 정기 재시작 윈도우 + 야간·주말 적재 작업 중 일시 중단 허용

### 5.2 트래픽 가정 — 잠정 추정

| 항목 | 추정 |
|---|---|
| 동시 Admin 사용자 | 1명 (단일 Admin) |
| 일일 신규·갱신 페이지 | 100~500건 (보도자료·공고 갱신 빈도 가정) |
| 단일 Job 최대 페이지 | 50,000 (docx §0.5 NFR) |
| 일일 첨부 다운로드 (`/files/{id}`) | 챗봇 트래픽에 종속 — 초기 수십 건/일 추정 |
| 챗봇 질의 (참고, Tiledesk 책임) | 본 시스템 측정 항목 아님 |

→ 운영 시작 후 실측치로 보정.

### 5.3 응답시간 목표

| 경로 | 목표 |
|---|---|
| Admin UI 페이지 로딩 | < 2s (사내망 기준) |
| `/api/*` 응답 (목록·상세) | < 500ms (95p) |
| `/files/{id}` 다운로드 | 첨부 크기에 비례. **첫 응답 < 1s** |
| `/api/qa` 검색 (챗봇) | **본 시스템 책임 아님** — Tiledesk-LLM 측 |

### 5.4 복구 (RTO / RPO)

#### 원칙: 백업 미운영
- source of truth는 원천 사이트. 손실 시 재크롤·재정제·재임베딩 복원 (docx §5.7)
- **RTO**: **7일 이내** — 도메인 한 곳 기준 `full` Job + 임베딩 비용 발생
- **RPO**: 마지막 incremental 시점까지 (주 1회 → 최대 7일)

#### Fallback SOP — KSPO IT 정책이 백업 운영을 요구하는 경우
운영 시작 전 KSPO IT 1회 합의로 결정. 거절 시 다음 SOP 적용:

| 자산 | 백업 대상 여부 | 방법 |
|---|---|---|
| `storage/raw` (영구 보관 raw HTML) | 백업 | 일일 rsync to KSPO NAS 또는 사내 백업 인프라 |
| `storage/refined` (LLM 정제 JSON) | 백업 | 일일 rsync (위와 동일) |
| `storage/attachments` (첨부 원본) | 백업 | 일일 rsync (위와 동일) |
| PG (메타) | 미백업 | 재크롤로 복원 |
| Redis (큐 상태) | 미백업 | 재시작 시 손실 허용 |
| Qdrant (벡터) | 미백업 | 재임베딩으로 복원 |

→ 백업 도입 시 RTO·RPO 목표는 KSPO IT 정책에 맞춰 재산정.

### 5.5 데이터 보존

- `storage/raw`, `storage/refined`, `storage/attachments` — **영구 보관** (docx §5.7 ✓)
- PG 메타·Qdrant — 운영 중에만, 손실 시 재크롤·재정제·재임베딩 복원

---

## 6. 인프라

### 6.1 호스팅 환경

- **사내 IDC** (온프레미스) ✓
- **망분리 환경**, OpenAI는 사내 프록시 경유 ✓
- **호스트 사양 — 권장 최소 (확인 필요)**

| 자원 | 권장 최소 | 비고 |
|---|---|---|
| CPU | 8 vCPU | api + worker + postgres + qdrant 동시 가동 |
| RAM | 16 GB | Qdrant 3072차원 컬렉션 + ARQ + Postgres 합산 |
| 디스크 | 200 GB SSD | `storage/` 영구 보관 (raw HTML + 첨부) — KSPO 콘텐츠 양에 따라 가변 |
| 네트워크 | 사내망 + 프록시 outbound | OpenAI 호출용 |

→ 운영 1~3개월 후 실측치로 조정.

**도입 방식 (잠정)**:
- **권장**: 기존 KSPO IDC 호스트 1대 활용 (사양 충족 시)
- 미충족 시: 신규 VM 1대 할당 — KSPO IT 자산팀 협의
- M0 시작 전 KSPO IT 자산팀과 1회 협의로 확정

### 6.2 프록시 (OpenAI 호출용)

| 항목 | 값 |
|---|---|
| **환경변수 이름** | `HTTPS_PROXY` (Linux 표준 — openai SDK·httpx 모두 자동 인식) ✓ |
| 보조 환경변수 | `HTTP_PROXY`, `NO_PROXY` ✓ |
| 프록시 호스트:포트 값 | 운영 시 `.env`에 KSPO 인프라팀 제공값 입력 (`http://<host>:<port>` 형식). `.env.example`에는 placeholder ✓ |
| 인증 방식 | 인증 없음 (anonymous) ✓ |
| TLS 인스펙션 | 없음 (CONNECT 중계만 — 사내 root CA 마운트 불필요) ✓ |
| 화이트리스트 | `api.openai.com` 만 (KSPO 인프라팀 측 정책) ✓ |
| 적용 범위 | OpenAI 호출만. 크롤은 사내망 직접 (`NO_PROXY` 분리) ✓ |
| `NO_PROXY` 기본값 | `localhost,127.0.0.1,postgres,redis,qdrant,host.docker.internal` + Admin이 등록한 KSPO 도메인 ✓ |
| 시작 시 검증 | `OPENAI_API_KEY` 설정 + `HTTPS_PROXY` 미설정 시 **warning 로그**(error 아님 — 사외 개발 환경 호환) ✓ |
| `OPENAI_BASE_URL` | 사용 안 함 — 표준 환경변수 방식이 SDK 호환성 우수 ✓ |

### 6.3 컨테이너 구성

```
name: kspo-ingest

services:
  nginx       — 정적자산(SPA dist) + reverse proxy (/api, /files) + TLS 종료
  api         — FastAPI (REST API only — Jinja2/HTMX 미사용)
  worker      — ARQ (queue: default, attach, bg)
  postgres    — 16-alpine
  redis       — 7-alpine
  qdrant      — Qdrant (개발·파일럿 단계 self-hosted; 정식 운영 시 종료+삭제)
  migrations  — profile, alembic upgrade head 1회

volumes:  pgdata, redisdata, qdrant_data, storage
networks: kspo-ingest-net
```

**전환 후(정식 운영) 구성**: `qdrant` 서비스 제거 → 5 services. `QDRANT_URL` 환경변수를 Tiledesk Qdrant로 변경.

#### Docker 배포 잠정 결정 (M0.T0.2 시점에 docker-compose·Dockerfile로 구체화)

> 본 표 12행은 **`docs/tasks/M0_T0_2.md` 머지 시점에 모두 구체화되어 코드(`docker/`, `docker-compose.yml`)로 옮겨졌다.** 이후 변경은 PRD가 아니라 해당 코드를 단일 진실원으로 본다. 본 표는 결정 근거 보존용.

| 항목 | 잠정 결정 | 비고 |
|---|---|---|
| **TLS 종료** | `nginx` 컨테이너에서 종료 (사내 인증서 마운트) | KSPO IT가 외부 LB 종료 선호 시 nginx는 HTTP만 |
| **frontend dist 전달** | `Dockerfile.web` multi-stage (Node 빌드 → nginx serve) | image에 dist를 COPY |
| **Node 버전** | 20 LTS | 빌드 단계만 사용 |
| **이미지 레지스트리** | 사내 레지스트리 우선 (Harbor·GitLab) | 미보유 시 로컬 빌드 + `docker save` tar 배포 |
| **재시작 정책** | `restart: unless-stopped` | docx §5.1 일치 |
| **로그 수집** | stdout (`docker logs`) | 추가 syslog·journal은 KSPO IT 운영 정책 결정 |
| **시간대** | 전 컨테이너 `TZ=Asia/Seoul` | docx §5.3 환경변수 일치 |
| **볼륨 방식** | named volume (`pgdata`/`redisdata`/`qdrant_data`/`storage`) | bind mount은 운영 시점 결정 |
| **포트 노출** | host 80/443 → nginx만. api 8080·Qdrant 6333은 사내망 only (compose 내부 네트워크) | 디버그 시 임시 expose 허용 |
| **outbound 프록시** | `HTTPS_PROXY` 환경변수 (api, worker 컨테이너만) | §6.2 |
| **gzip·캐시 헤더** | nginx 기본값 + 정적자산은 `Cache-Control: public, max-age=31536000, immutable` (Vite hashed filename 전제) | nginx config에 명시 |
| **`/files/{id}` 처리** | nginx → api 단순 reverse proxy | 대용량 트래픽 발생 시 `X-Accel-Redirect`로 오프로드(Tier 2) |

### 6.4 보안

| 항목 | 결정 |
|---|---|
| TLS 종료 위치 | **nginx 컨테이너에서 종료** (사내 인증서 마운트). KSPO IT가 외부 LB 종료 선호 시 변경 가능 (M0.T0.2 시점 협의) |
| 이미지 레지스트리 | **사내 레지스트리 우선** (Harbor·GitLab). 미보유 시 로컬 빌드 + `docker save` tar 배포. Docker Hub 직접 풀은 망분리 환경상 불가 가정 |
| 컴플라이언스 (CSAP / ISMS-P) | **비대상 가정** — 공개자료만 다루는 내부 도구. 점검 시 KSPO IT 보안팀 확인 |
| 시크릿 관리 | `.env` chmod 600, git 미포함, 호스트 권한자만 접근 (docx §1.6 / `CLAUDE.md`) ✓ |
| 외부 API TLS 검증 | 활성 (CONNECT only 프록시 기준) ✓ |
| 컨테이너 간 통신 | compose 내부 네트워크만 (`kspo-ingest-net`). nginx만 host 80/443 노출 ✓ |

### 6.5 인증·세션

- 인증: 단일 Admin, HTTP Basic Auth → 세션 (bcrypt cost ≥ 12) ✓
- **세션 만료**: 8시간 (일과 기준) ✓
- **IP 화이트리스트**: 적용 안 함 (사내망 경계) ✓
- **계정 복구**: 호스트 접근 권한자가 `.env` 직접 수정 ✓

---

이전: [§4 솔루션](./04_solution.md) · 다음: [§7 비용·§8 일정](./06_cost_schedule.md)
