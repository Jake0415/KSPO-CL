"""KSPO 크롤 데이터 → Sonar 챗봇 KB 적재 어댑터.

우리 Qdrant(로컬 컨테이너)의 정제 텍스트(page_content)를 source URL별로 묶어,
Sonar-server의 KB API(`POST /:projectid/kb`, type=txt)로 밀어넣는다. Sonar가
자체 임베딩(ada-002 1536) + sparse + namespace로 인덱싱까지 자동 수행하므로,
챗봇이 곧바로 검색·답변에 사용한다.

우리가 직접 넣은 tilellm(3072)은 Sonar가 못 쓴다(차원 불일치) → 이 경로가 정식.

사용법:
    python scripts/push_to_sonar.py \
        --sonar-base http://223.130.163.224:8081 \
        --project-id 6a44a7129f4e240013784d4f \
        --namespace 6a44a7129f4e240013784d4f \
        --email <대시보드_로그인_이메일> \
        --password <대시보드_비밀번호> \
        --source-qdrant http://localhost:6333 \
        --collection kspo_knowledge \
        [--limit 5]      # 테스트: 처음 N개만
        [--dry-run]      # 전송 없이 뭘 보낼지 미리보기

인증: Sonar 대시보드 로그인 계정(이메일/비번)으로 Basic Auth. admin 역할 필요.
      또는 --token <JWT> 로 Bearer 토큰 직접 지정 가능.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from collections import OrderedDict


def _req(url: str, *, method="GET", headers=None, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
        return resp.status, raw


def _auth_header(args) -> dict:
    if args.token:
        return {"Authorization": f"Bearer {args.token}"}
    if args.email and args.password:
        cred = base64.b64encode(f"{args.email}:{args.password}".encode()).decode()
        return {"Authorization": f"Basic {cred}"}
    raise SystemExit("인증 필요: --email/--password 또는 --token 을 지정하세요.")


def _scroll_source(qdrant_url: str, collection: str):
    """우리 Qdrant를 스크롤하며 (source_url, title, page_content) 산출."""
    offset = None
    while True:
        body = {"limit": 256, "with_payload": True, "with_vector": False}
        if offset:
            body["offset"] = offset
        status, raw = _req(
            f"{qdrant_url}/collections/{collection}/points/scroll",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=body,
        )
        result = json.loads(raw)["result"]
        for p in result["points"]:
            pl = p.get("payload", {}) or {}
            md = pl.get("metadata", {}) or {}
            yield md.get("source", ""), md.get("title", ""), pl.get("page_content", "")
        offset = result.get("next_page_offset")
        if not offset:
            break


def _group_by_source(qdrant_url: str, collection: str) -> OrderedDict[str, dict]:
    """source URL별로 page_content를 합쳐 문서 단위로 만든다.

    같은 URL의 여러 청크는 순서대로 이어붙인다(Sonar가 다시 청킹함). 제목은 첫 청크.
    """
    docs: OrderedDict[str, dict] = OrderedDict()
    for source, title, content in _scroll_source(qdrant_url, collection):
        if not source or not content.strip():
            continue
        d = docs.get(source)
        if d is None:
            docs[source] = {"title": title or source, "parts": [content.strip()]}
        else:
            d["parts"].append(content.strip())
    return docs


def _post_kb(args, headers, name: str, content: str, source: str) -> tuple[bool, str]:
    # 프록시(8081)는 /api/ 접두사를 떼고 sonar-server(:3000)로 전달한다.
    # sonar-server 라우트는 /:projectid/kb → 외부 호출 경로는 /api/{projectid}/kb.
    url = f"{args.sonar_base}/api/{args.project_id}/kb"
    payload = {
        "name": name[:200],
        # type='text'는 sonar-llm의 크롤 목록(url/txt/md/...)에 없어 else 분기로 가서
        # content를 "직접" 인덱싱한다. 'txt'로 보내면 source URL을 재크롤해(우리 텍스트
        # 무시) 로그인/JS 페이지에서 실패한다 — 검증 완료.
        "type": "text",
        "content": content,
        "source": source,
        "namespace": args.namespace,
        "tags": ["kspo", "ingest"],
    }
    try:
        status, raw = _req(
            url,
            method="POST",
            headers={**headers, "Content-Type": "application/json"},
            body=payload,
        )
        return 200 <= status < 300, f"{status} {raw[:120]}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:150]}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description="KSPO → Sonar KB 적재")
    ap.add_argument("--sonar-base", required=True, help="예: http://223.130.163.224:8081")
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--email", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--token", default="", help="JWT (email/password 대신)")
    ap.add_argument("--source-qdrant", default="http://localhost:6333")
    ap.add_argument("--collection", default="kspo_knowledge")
    ap.add_argument("--limit", type=int, default=0, help="처음 N개 문서만 (0=전체)")
    ap.add_argument("--sleep", type=float, default=0.3, help="요청 간 간격(초)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    headers = {} if args.dry_run else _auth_header(args)

    print(f"소스: {args.source_qdrant}/{args.collection}")
    print(f"대상: {args.sonar_base}/{args.project_id}/kb  (namespace={args.namespace})")
    print("문서 그룹핑 중…")
    docs = _group_by_source(args.source_qdrant, args.collection)
    items = list(docs.items())
    if args.limit:
        items = items[: args.limit]
    print(f"적재 대상 문서: {len(items)}개 (dry_run={args.dry_run})\n")

    ok = fail = 0
    for i, (source, d) in enumerate(items, 1):
        content = "\n\n".join(d["parts"])
        name = d["title"]
        if args.dry_run:
            print(f"[{i}/{len(items)}] {name[:40]}  ({len(content)}자)  <- {source[:55]}")
            if i <= 2:
                print(f"      content 미리보기: {content[:120]}…")
            continue
        success, msg = _post_kb(args, headers, name, content, source)
        if success:
            ok += 1
        else:
            fail += 1
            print(f"  [실패 {i}] {source[:50]} — {msg}")
        if i % 25 == 0:
            print(f"  진행 {i}/{len(items)} (성공 {ok}, 실패 {fail})")
        time.sleep(args.sleep)

    print("\n" + "=" * 50)
    if args.dry_run:
        print(f"DRY-RUN 완료: {len(items)}개 문서 전송 예정")
    else:
        print(f"완료: 성공 {ok}, 실패 {fail} / 총 {len(items)}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
