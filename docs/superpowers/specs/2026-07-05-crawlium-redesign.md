# KSPO Ingest Architecture Redesign — Crawlium Integration

## 1. 기존 프로젝트 분석

### 현재 구조
```
kspo_ingest/
├── api/           — FastAPI REST (14 endpoints)
├── attach/        — Attachment discovery/MIME
├── chunk/         — Text chunking (2-stage)
├── clean/         — HTML extraction (4-stage fallback)
├── crawl/         — Fetcher, Playwright, Frontier, Board, Links
├── db/            — SQLAlchemy 2.0 async models (7 tables)
├── embed/         — OpenAI embeddings
├── evaluation/    — LLM comparison
├── observability/ — Loguru, cost monitor, email alerts
├── qa/            — Citation
├── qdrant/        — Direct adapter
├── refine/        — LLM refinement (pre-rules + structured output)
└── tasks/         — ARQ worker, pipeline (BFS + incremental)
```

### 주요 비효율

1. **Fetcher**: 매 요청마다 `httpx.AsyncClient` 생성/파괴 — 커넥션 풀 낭비
2. **PlaywrightFetcher**: KSPO 특정 호스트 설정 하드코딩, 범용성 없음
3. **Selector**: YAML blacklist 기반 정적 제거만 — DOM 변경 대응 불가
4. **BFS Loop**: 순차 처리 — fetch→clean→refine→chunk 직렬, 동시성 미활용
5. **Stealth 없음**: UA 스푸핑만 — TLS fingerprint, timing 등 미대응
6. **Proxy 없음**: 단일 IP 크롤링
7. **AI Agent 없음**: 동적 페이지 상호작용 불가
8. **Plugin 없음**: 확장 구조 없음
9. **CLI 없음**: API로만 조작 가능
10. **Metrics 없음**: 로그 기반만

## 2. Scrapling 채택 사항

| 채택 | 원본 | 개선 |
|------|------|------|
| Adaptive Selector | 요소 fingerprint + similarity | 가중치 조정 가능, DB 저장 |
| Stealth Profile | TLS fingerprint, browser impersonation | 프로파일 기반 분리 |
| Proxy Rotation | Cyclic rotation | 헬스체크 + weighted rotation |
| Session Management | Cookie persistence | 호스트별 세션 풀 |
| Spider Framework | Scrapy-style callbacks | asyncio native, concurrent |

## 3. browser-use 채택 사항

| 채택 | 원본 | 개선 |
|------|------|------|
| AI Agent | LLM-driven task execution | Tool calling + DOM snapshot |
| Action System | Browser action definitions | 플러그인 확장 가능 |
| Task Planner | Multi-step decomposition | 재계획 + 자기수정 |
| Memory | Conversation history | 요약 기반 장기 기억 |
| Tool Registry | Custom tool extension | 데코레이터 기반 등록 |

## 4. 새 아키텍처

```
kspo_ingest/
├── api/              # 유지
├── attach/           # 유지
├── chunk/            # 유지
├── clean/            # 유지 + selector 연동 강화
├── crawl/            # REFACTOR
│   ├── fetcher.py    # 커넥션 풀, 재사용
│   ├── browser.py    # 범용 Playwright (stealth 통합)
│   ├── stealth.py    # 스텔스 프로파일
│   ├── selector.py   # Adaptive CSS selector
│   ├── spider.py     # Async spider (concurrent BFS)
│   ├── proxy.py      # Proxy rotation + healthcheck
│   ├── session_mgr.py # 세션 관리 추상화
│   ├── checkpoint.py # Crawl 체크포인트/재개
│   ├── frontier.py   # 유지
│   ├── board.py      # 유지
│   ├── internal_links.py # 유지
│   ├── rate_limit.py # 유지 (Lua script 강화)
│   ├── robots.py     # 유지
│   ├── storage.py    # 유지
│   ├── url_normalize.py # 유지
│   ├── family_sitemap.py # 유지
│   ├── nfa_video.py  # 유지
│   └── youtube_caption.py # 유지
├── agent/            # NEW
│   ├── agent.py      # AI 에이전트 오케스트레이터
│   ├── planner.py    # 작업 분해 + 단계 계획
│   ├── memory.py     # 단기/장기 메모리
│   ├── tools.py      # 도구 레지스트리
│   ├── actions.py    # 브라우저 액션
│   └── prompts.py    # 프롬프트 템플릿
├── platform/         # NEW
│   ├── cli.py        # Typer CLI
│   ├── plugins.py    # 플러그인 시스템
│   └── metrics.py    # Prometheus 메트릭
├── db/               # 유지
├── embed/            # 유지
├── evaluation/       # 유지
├── observability/    # 유지
├── qa/               # 유지
├── qdrant/           # 유지
├── refine/           # 유지
└── tasks/            # 유지 + spider/agent 연동
```

## 5. 핵심 설계 결정

- 기존 파이프라인(fetch→clean→refine→chunk→index) 유지
- `crawl/fetcher.py` — AsyncClient 싱글톤 + 커넥션 풀
- `crawl/browser.py` — PlaywrightFetcher 범용화 + stealth 통합
- `crawl/selector.py` — Scrapling 영감 adaptive selector (fingerprint + similarity)
- `crawl/spider.py` — 기존 enqueue_seeds BFS를 concurrent로 리팩터
- `agent/` — browser-use 영감 AI 에이전트 (자연어 → 브라우저 자동화)
- 모든 신규 모듈은 기존 모듈과 느슨한 결합
- 기존 테스트 335개 통과 유지 목표

## 6. 신규 의존성

- `typer` — CLI
- `prometheus-client` — 메트릭
- `playwright-stealth` — 브라우저 스텔스 (또는 커스텀)
- `litellm` — 다중 LLM 프로바이더 (agent용)
- `difflib` — stdlib, adaptive selector similarity
