# Tiledesk 챗봇 ↔ 우리 벡터 연동 확인 — 실행 명령어 모음

> 목적: 우리가 운영 Qdrant(`223.130.163.224:6333`)에 넣은 `tilellm`(3072차원) 벡터를
> Tiledesk 챗봇이 실제로 읽게 하려면, Tiledesk의 (1)컬렉션 이름 (2)임베딩 모델을
> 알아야 한다. 아래 명령어로 하나씩 확인한다.
>
> **어디서 실행?** — `223.130.163.224` 서버에 접속(SSH/콘솔)한 뒤, 그 서버의 터미널에서.
> 각 명령 결과를 복사해서 개발자(무한아이티)에게 전달하면 된다.

---

## STEP 0. 서버 접속
KSPO/네이버클라우드 콘솔 또는 SSH로 `223.130.163.224` 서버에 로그인.
(SSH가 열려 있으면: `ssh <계정>@223.130.163.224`)

접속 후, Tiledesk가 도커로 돌고 있는지 먼저 본다:
```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}' | grep -iE 'tiledesk|llm|qdrant|sonar'
```
→ `tiledesk-*` 또는 `*-llm-*` 이름의 컨테이너가 보이면 그게 Tiledesk다.

---

## STEP 1. Tiledesk-LLM이 어느 Qdrant를 보는지 (가장 중요)
Tiledesk-LLM 컨테이너의 환경변수를 본다. (컨테이너 이름은 STEP 0에서 확인한 것으로 교체)
```bash
# 예: 컨테이너 이름이 tiledesk-llm 이라면
docker exec tiledesk-llm env | grep -iE 'QDRANT|QDRANT_URL|VECTOR|COLLECTION|EMBED|OPENAI'
```
찾을 값:
- `QDRANT_URL` — `...:6333` 이면 우리와 같은 Qdrant ✅
- 컬렉션 이름 관련 변수 (있을 수도, 없을 수도)

---

## STEP 2. 임베딩 모델·차원 확인 (차원 안 맞으면 재임베딩 필요)
```bash
docker exec tiledesk-llm env | grep -iE 'EMBED|MODEL|DIM|1536|3072|text-embedding|ada'
```
찾을 값:
- `text-embedding-3-large` → 3072차원 → **우리와 동일, 그대로 사용 가능** ✅
- `text-embedding-3-small` / `text-embedding-ada-002` → 1536차원 → **차원 불일치, 재임베딩 필요** ⚠️

> 참고: 우리가 넣은 `tilellm` = 3072차원.
> 서버의 기존 `tiledesk-llm` 컬렉션 = 1536차원(named vector `text-dense`).
> → 이 둘은 차원이 달라 그대로 호환 안 됨. Tiledesk가 어느 쪽을 쓰는지가 관건.

---

## STEP 3. Tiledesk 관리화면에서 "지식/데이터소스" 설정 확인
브라우저로 Tiledesk 대시보드(`http://223.130.163.224:8081` 계열) 로그인 후:
1. 챗봇/프로젝트 → **Knowledge Base(지식베이스)** 또는 **AI/LLM 설정** 메뉴
2. 거기에 **컬렉션 이름**과 **임베딩 모델**이 표시됨 → 스크린샷

---

## STEP 4. Qdrant에서 Tiledesk가 실제 쓰는 컬렉션 직접 조회
서버(또는 접근 가능한 곳)에서:
```bash
# 컬렉션 목록
curl -s http://223.130.163.224:6333/collections | python3 -m json.tool

# 각 컬렉션의 차원 확인
for c in tilellm tiledesk-llm; do
  echo "=== $c ==="
  curl -s "http://223.130.163.224:6333/collections/$c" \
    | python3 -c "import sys,json; d=json.load(sys.stdin)['result']; print('points:',d['points_count']); print('vectors:',d['config']['params']['vectors'])"
done
```

---

## 결과에 따른 판단 (개발자에게 전달용)

| STEP 1·2 결과 | 의미 | 다음 조치 |
|---|---|---|
| Tiledesk가 `tilellm` + 3072차원 사용 | 완벽 호환 | **끝. 그대로 작동** ✅ |
| Tiledesk가 `tiledesk-llm` 컬렉션 사용 | 우리 데이터를 안 봄 | 우리 데이터를 `tiledesk-llm`로 재적재 OR Tiledesk 설정을 `tilellm`으로 변경 |
| Tiledesk 임베딩이 1536차원 | 차원 불일치 | **재임베딩 필요** — 같은 1536 모델로 우리 문서 다시 임베딩 |

---

## 요약: 개발자에게 이 3가지만 알려주면 됨
1. **Tiledesk-LLM의 `QDRANT_URL`** (STEP 1)
2. **Tiledesk-LLM이 읽는 컬렉션 이름** (STEP 1·3)
3. **Tiledesk-LLM의 임베딩 모델 이름** (STEP 2·3)
