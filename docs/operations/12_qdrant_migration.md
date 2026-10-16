# Qdrant 데이터 이관 — 운영 서버로 전환

> 개발/파일럿 컨테이너 Qdrant(`localhost:6333`)의 적재 데이터를
> **운영 Qdrant(Tiledesk 등 외부 인스턴스)**로 옮기는 절차.
> PRD "듀얼 모드" 설계(`QDRANT_URL` 토글) 구현.

## 현재 적재 규모 (2026-07-19 기준)
| 컬렉션 | 벡터 수 | 구성 |
|---|---|---|
| tilellm | ~4,900 | 3072-dim, Cosine, on_disk, INT8 양자화 |
| kspo_knowledge | ~5,600 | 동일 |
| kspo_archive | 0 | 동일 |

## 방식 선택
운영 서버는 보통 **파일 접근이 막힌 관리형/원격 인스턴스**라, snapshot(파일 기반)
대신 **HTTP scroll + upsert** 방식을 쓴다. point ID·벡터·payload를 그대로 보존하며,
컬렉션 설정과 payload 인덱스를 소스에서 읽어 타깃에 동일 생성한다.

스크립트: `scripts/qdrant_migrate.py`

## 절차

### 1. 운영 Qdrant 접속 정보 확보
Tiledesk(또는 운영팀)로부터:
- `TARGET_URL` — 예: `https://qdrant.prod.example:6333`
- `TARGET_API_KEY` — 인증 키

### 2. 연결 확인 (읽기 전용)
```bash
curl -s -H "api-key: <TARGET_API_KEY>" <TARGET_URL>/collections
```
→ 200 + 컬렉션 목록(비어있어도 정상)이면 연결 OK.

### 3. Dry-run (쓰기 없이 소스 개수만 확인)
```bash
docker exec kspo-worker-1 python /app/scripts/qdrant_migrate.py \
  --source-url http://qdrant:6333 --source-key "$QDRANT_API_KEY" \
  --target-url <TARGET_URL> --target-key <TARGET_API_KEY> --dry-run
```

### 4. 실제 이관
```bash
docker exec kspo-worker-1 python /app/scripts/qdrant_migrate.py \
  --source-url http://qdrant:6333 --source-key "$QDRANT_API_KEY" \
  --target-url <TARGET_URL> --target-key <TARGET_API_KEY> \
  --collections tilellm,kspo_knowledge,kspo_archive
```
- 각 컬렉션마다 `소스=N 복사=N 타깃=N ✅` 로 **개수 일치 검증**까지 출력.
- 타깃에 같은 이름 컬렉션이 이미 있으면 중단됨 → 덮어쓰려면 `--recreate` 추가.
  (운영 컬렉션 이름이 다르면 애초에 충돌 없음.)

### 5. 앱을 운영 Qdrant로 전환
`.env`에서 주소만 바꾸고 컨테이너 재시작 — 코드 변경 없음(듀얼 모드):
```
QDRANT_URL=<TARGET_URL>
QDRANT_API_KEY=<TARGET_API_KEY>
```
```bash
docker compose -f docker/docker-compose.yml up -d api worker
```
- 이후 크롤·검색이 운영 Qdrant를 대상으로 동작.
- (선택) 운영 전환 후 개발 컨테이너 qdrant 서비스 제거 → 7개→6개 컨테이너.

## 검증 체크리스트
- [ ] 대상 컬렉션 3개 개수가 소스와 일치 (스크립트가 자동 확인)
- [ ] 샘플 검색 1건: `/api/qa`가 운영 Qdrant로 정상 응답
- [ ] payload 인덱스 존재 확인 (`domain_host` 필터, `page_content` 전문검색)

## 주의
- **외부 운영 서버에 쓰는 작업**이다. TARGET_URL/KEY를 반드시 재확인하고 실행.
- 이관 중 개발 크롤을 멈춰 소스가 변하지 않게 하면 개수 검증이 깔끔하다.
- 네트워크 단절로 중단돼도 upsert는 멱등(같은 ID 덮어씀)이라 **재실행하면 이어서/다시** 안전.
