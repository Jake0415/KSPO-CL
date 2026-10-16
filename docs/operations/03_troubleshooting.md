# 자주 발생하는 문제 (런북 A/B/C 미해당)

> 사고 시나리오는 `docs/runbook/A,B,C` 참조. 본 문서는 그 외의 운영 빈발 상황.

## Q1: Job이 PENDING 상태에서 진전이 없음

**원인 후보**
- worker 컨테이너 미가동
- Redis 연결 실패
- ARQ queue name 미스매치 (M3 시점에 한 번 발생, 현재는 fix됨)

**진단**
```bash
docker compose ps worker
docker compose logs worker --tail=80
docker compose exec redis redis-cli LLEN arq:queue
```

**조치**
- `docker compose restart worker`
- 30초 후 다시 ARQ queue 길이 확인 — 줄어들면 정상
- 지속되면 [Q3](#q3-redis-연결-실패) 참조

## Q2: 페이지 본문 추출 실패 (DROPPED `too_short`)

**원인 후보**
- 동적 렌더링 페이지(JS) — Trafilatura가 빈 본문만 봄
- 보일러플레이트가 본문보다 큰 페이지

**진단**
- `pages/{id}` 상세 → Raw HTML 탭 (M5.T5.4 결선) 또는 직접 `cat storage/raw/{domain_id}/{url_hash}.html`
- 본문 텍스트가 실제로 비어 있는지 또는 메뉴/푸터만 있는지 확인

**조치**
- 동적 페이지: `use_playwright=true` (Tier 2 — 현 v2.1 미지원)
- 보일러플레이트: 도메인 `selector_blacklist`에 셀렉터 추가 (예: `.gnb, footer, #snb`)
- 사이트 차원 차단: 페이지를 의미 있는 답변에 못 쓰는 걸로 판단되면 `deny_patterns`로 차단

## Q3: Redis 연결 실패

**증상** — worker 시작 실패, api `/readyz` redis 항목 fail

```bash
docker compose ps redis
docker compose logs redis --tail=20
docker compose exec api curl -sS redis:6379 || echo "redis unreachable"
```

**조치**
- redis 컨테이너 재시작: `docker compose restart redis`
- `.env` `REDIS_URL` 형식 확인 (`redis://redis:6379/0`)
- 디스크 가득 → `docker system df`

## Q4: 검색 품질 저하 (Tiledesk 측 보고)

**원인 후보**
- 청크 토큰 길이 분포 비정상 (헤더 포함 800+ 토큰 다수)
- `summary` 필드 비어있는 청크 다수
- 카테고리 필터 부재로 무관 청크가 top-k 진입

**진단**
```sql
-- token 분포
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY token_len) AS p50,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY token_len) AS p95
  FROM chunks WHERE kb_status='OK';

-- summary 비어있는 비율
SELECT COUNT(*) FILTER (WHERE summary IS NULL OR summary='') / COUNT(*)::float AS empty_pct
  FROM (SELECT (payload->'metadata'->>'summary') AS summary FROM ... ) t;
```

**조치**
- p95 token_len > 1000 → `chunk_long_threshold_tokens` / `chunk_target_tokens` 재튜닝 (Tier 2)
- summary 비어있음 다수 → refine 모델 응답 검증 (`gpt-5.4-mini` 출력 품질)
- 카테고리 필터: Tier 2 — 운영 측정 후 도입 검토

## Q5: 디스크 사용량 급증

**원인 후보** — `storage/raw/` 영구 보관 정책

**진단**
```bash
du -sh storage/raw storage/refined
df -h /var/lib/docker/volumes/
docker system df
```

**조치**
- **단기** — 무관한 도메인 비활성화로 Qdrant 청크 제거 (디스크 영향 작음)
- **중기** — `storage/raw/` 압축 (Tier 2 — `*.html.zst` 변환 worker)
- **장기** — KSPO NAS rsync 보강, 호스트 디스크는 30일 윈도우만 보존
- 백업 미운영이므로 **삭제는 비가역** — 운영 결정 후에만 진행

## Q6: 빌드/배포 실패 (`pip install -e .`)

`README.md` 누락 → `setup_metadata` 에러 (M3 E2E 시 한 번 발견됨, fix됨).

```bash
docker compose build --no-cache api worker
```

전체 클린 빌드. 그래도 실패하면 [docs/runbook/deploy.md §11](../runbook/deploy.md) 참조.

## Q7: 마이그레이션 충돌

여러 개발자가 동일 down_revision으로 alembic revision 작성 시.

```bash
alembic heads   # 두 개 이상이면 충돌
alembic merge -m "merge heads" <head1> <head2>
docker compose --profile migrations run --rm migrations
```

## Q8: 비밀번호 분실

`.env`의 `ADMIN_PASSWORD_BCRYPT`를 새 해시로 교체 후 api 재시작:

```bash
docker run --rm python:3.12 sh -c \
  'pip install -q bcrypt && python -c "import bcrypt, getpass; print(bcrypt.hashpw(getpass.getpass(\"new pw: \").encode(), bcrypt.gensalt(12)).decode())"'
```

해시를 `.env`에 붙이고 `docker compose up -d --force-recreate api worker`. 기존 세션 모두 무효 — 모든 사용자 재로그인.

## Q9: 도메인 비활성화 후 재활성화

`PATCH /api/domains/{id}` `is_active=false` → Qdrant 청크 + 페이지 일괄 REMOVED.
다시 `is_active=true`만 해서는 청크가 자동 복원되지 않음. **재크롤 필요**:

```bash
curl -X POST -b session http://localhost/api/jobs/full/{domain_id}
```
