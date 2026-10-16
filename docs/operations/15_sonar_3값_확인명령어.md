# Sonar 연동 3값 확인 명령어 (임베딩·namespace·컬렉션)

> Sonar 구조 (소스 분석 확정):
> - 컬렉션 = `engine.index_name`, 벡터 = named `text-dense`(+`text-sparse`)
> - namespace = payload 키 `metadata.namespace` (한 컬렉션에 여러 namespace 공존)
> → 실제 저장된 데이터를 들여다보면 3값이 다 나온다.

---

## 방법 A: 이 맥(로컬)에서 바로 실행 — 가장 쉬움
아래를 **그대로 복사해서** 이 맥 터미널에 붙여넣으세요. (서버 6333이 열려 있어 접근 가능)

```bash
python3 - <<'PY'
import json, urllib.request
BASE="http://223.130.163.224:6333"
def get(p):
    return json.load(urllib.request.urlopen(BASE+p, timeout=10))
# 1) 컬렉션 목록 + 각 벡터 차원/구조
cols=[c["name"] for c in get("/collections")["result"]["collections"]]
print("=== 컬렉션 목록 ===", cols)
for c in cols:
    d=get(f"/collections/{c}")["result"]
    print(f"\n[{c}] points={d['points_count']}")
    print("  vectors config:", json.dumps(d["config"]["params"]["vectors"], ensure_ascii=False))
# 2) 각 컬렉션에서 실제 포인트 1개 열어 namespace/임베딩모델 확인
for c in cols:
    body=json.dumps({"limit":1,"with_payload":True,"with_vector":False}).encode()
    req=urllib.request.Request(f"{BASE}/collections/{c}/points/scroll",data=body,headers={"Content-Type":"application/json"})
    pts=json.load(urllib.request.urlopen(req,timeout=10))["result"]["points"]
    if not pts: 
        print(f"\n[{c}] (비어있음)"); continue
    md=(pts[0].get("payload",{}) or {}).get("metadata",{}) or {}
    print(f"\n[{c}] 샘플 payload.metadata 키:", list(md.keys()))
    print("   namespace =", md.get("namespace"))
    print("   embedding/model 관련:", {k:v for k,v in md.items() if any(t in k.lower() for t in ("embed","model","dim"))})
    print("   source =", str(md.get("source"))[:60])
PY
```

**결과에서 읽을 것:**
- **컬렉션 이름** = 위 목록 (`tiledesk-llm` 등 — 우리 `tilellm` 말고 Sonar가 쓰는 것)
- **벡터 차원** = `vectors config`의 `size` (예: `text-dense: 1536` → 1536차원)
- **namespace** = 샘플의 `namespace =` 값 (챗봇이 읽는 실제 namespace)

---

## 방법 B: 서버에서 실행 (방법 A가 막히면)
서버에 접속 후, wget이 없으니 python 컨테이너로 조회:
```bash
docker exec sonar-llm-qa python -c "
import urllib.request,json
b='http://sonar-qdrant-1:6333'
try: r=json.load(urllib.request.urlopen(b+'/collections',timeout=8))
except Exception:
    b='http://localhost:6333'; r=json.load(urllib.request.urlopen(b+'/collections',timeout=8))
print('BASE=',b)
for c in r['result']['collections']:
    n=c['name']; d=json.load(urllib.request.urlopen(f'{b}/collections/{n}',timeout=8))['result']
    print(n,'points=',d['points_count'],'vectors=',d['config']['params']['vectors'])
"
```

---

## 방법 C: 관리자 대시보드에서 (비개발자용)
브라우저로 Sonar 대시보드 로그인 →
1. 해당 KSPO 챗봇/프로젝트 열기
2. **Knowledge Base / 지식 / Data Source / AI설정** 메뉴
3. 거기 표시된 **임베딩 모델**과 **컬렉션/namespace** → 스크린샷

---

## 3값 매핑 (결과 → 연동 스크립트 입력)
| 확인할 값 | 어디서 | 연동 스크립트에 넣을 곳 |
|---|---|---|
| ① 임베딩 모델·차원 | vectors config의 size, payload의 embedding | `ItemSingle.embedding`, `engine.vector_size` |
| ② namespace | payload `metadata.namespace` | `ItemSingle.namespace` |
| ③ 컬렉션명 | 컬렉션 목록 | `engine.index_name` |

→ 이 3값 확정되면 KSPO 텍스트를 Sonar `/api/scrape/single`로 적재하는 스크립트 착수 가능.
