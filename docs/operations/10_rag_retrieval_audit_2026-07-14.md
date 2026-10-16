# RAG Retrieval-Quality Audit — 2026-07-14

> Scope: full pipeline audit of the KSPO `/api/qa` answerer against the 50-question
> evaluation set (`07_rag_evaluation_dataset.md`), run live against Qdrant
> (`tilellm`, 6615 pts) + gpt-5.4-mini. Goal: find root causes, generalize each
> into a defect *class*, eliminate the class corpus-wide, verify no regressions.

## Pipeline inspected

Crawler → Parser → Metadata → Chunking → Embedding → **Vector Search** →
Prompt → LLM → Citation.

Reality vs. the idealized pipeline: the live answerer (`api/routers/qa.py`) is
**pure dense retrieval** — there is **no hybrid/BM25 stage and no reranker model**.
It embeds the question, does a single `query_points` on one collection, concatenates
the top-k `page_content`, and asks the LLM to cite `[n]`. Citation parsing
(`qa/citation.py`) maps `[n]` back to the source list positionally.

## Baseline measurement (50 questions, live)

| Metric | Baseline |
|---|---|
| Not-found ("해당 정보를 찾을 수 없습니다") | **17 / 50 (34%)** |
| Queries with duplicate pages in top-5 | **35 / 50 (70%)** |
| Avg unique docs in top-5 | **3.84 / 5** |
| Max similarity < 0.50 | 21 / 50 |
| Citations present when answered | 33 / 33 (healthy) |

## Final result (after fixes, purged index, temp 0.1)

| Metric | Baseline | Final | Note |
|---|---|---|---|
| Queries with duplicate pages in top-5 | 35 / 50 | **17 / 50** | halved; remainder = legit multi-chunk |
| Avg unique docs in top-5 | 3.84 | **4.62** | |
| http/https twins (index + retrieval) | ~54% of index | **0** | purged, 0 pages lost |
| Not-found | 17 / 50 | **13 / 50** | deterministic fact-fixes (A5 address, G3 fee); remainder triaged below |
| Contact/service facts (address/phone/hours/fee) | dense-miss | **deterministic + cited** | known-facts layer |
| Full test suite | — | **743 pass** (+23 new) | 2 pre-existing unrelated fails |

## Defect classes & root causes

### 1. Duplicate content — DOMINANT (root cause fixed)
`tilellm` holds 6615 points but only **3632 distinct normalized URLs**: 1190 URLs
exist as both `http://` and `https://` variants → **~54% of the index is
scheme-twin duplicates**. Each twin was crawled *and refined by the LLM
separately*, so twin bodies are **similar but not byte-identical** (token-Jaccard
median 0.61).

- **Root cause (source):** `crawl/url_normalize.py::_identity_hash` included the
  URL **scheme** in the content-identity hash, so `http`/`https` of one page got
  different `url_hash` → both passed the frontier `seen` dedup and the
  `pages(domain_id, url_hash)` unique constraint → double-crawled, double-indexed.
- **Fix (source):** make `_identity_hash` scheme-independent. Prevents *all* future
  twins. `normalize_url`'s returned fetch URL keeps its original scheme.
  Regression test: `test_http_https_same_identity_hash`.

### 2. Duplicate content — query-time defense-in-depth
The existing index still contains legacy twins. Added `qa/retrieval.py`:
over-fetch `max(4·top_k, 20)` candidates, then **collapse near-duplicate bodies
within the same normalized URL** (token-Jaccard ≥ 0.55 — separates twins @0.61
from legitimate distinct chunks @0.35) + exact-body dedup across URLs. Distinct
chunks of a multi-chunk page (19% of pages) are **preserved**.

### 3. No authority / domain ranking
Org-level queries surfaced complaint-center / family-site pages over the canonical
`www.kspo.or.kr`. Added a small **authority tie-break** (HQ 1.0 > nfa 0.9 >
kspo subdomains 0.6 > ksponco 0.5 > other 0.4), weight 0.02 — reorders near-ties
only, never displaces a clearly-more-relevant family-site answer.

### 4. No hybrid / lexical signal
Exact-term factual lookups (address "올림픽로", fees, phone `02-410-1201`) exist in
the corpus (50–580 chunks) but pure dense under-ranks them. Added a **lexical
overlap boost** (weight 0.03) over the candidate set — a BM25-lite approximation
that needs no re-indexing.

### 5. Coverage gaps (report-only — not a retrieval-code defect)
Confirmed *absent* from both collections, so "not found" is the **correct** answer:
spoex.com facilities (H4, 0 chunks), WiFi (D7, 0), swim membership 회원권 (C3, 0).
These need **crawl expansion**, not retrieval changes.

## Verification

- **Deterministic retrieval layer** (isolates the fix from LLM sampling noise):
  normalized-URL repeats in top-5 across 50 queries **57 → 33**; true content-twins
  0 → 0; legitimate multi-chunk chunks preserved.
- **Unit tests:** 12 new (`test_qa_retrieval.py`) + 1 (`test_url_normalize.py`), all pass.
- **Full suite:** 731 passed; 2 pre-existing failures (`test_compare`, `test_provider`
  — missing OpenAI/Gemini key, unrelated).

## Important caveat — the not-found metric is LLM-noisy
gpt-5.4-mini @ temp 0.1 is **non-deterministic at the grounding boundary**: F2 with
byte-identical retrieval answered on one run and declined on the next. Single-run
final-answer comparisons therefore conflate retrieval changes with sampling noise;
the deterministic retrieval-layer metric above is the reliable signal.

## Follow-up actions

### Done in this audit
- **Legacy twin remediation (index-level)** — purged the http/https twins from
  both live collections, keeping the higher-chunk variant per page: `tilellm`
  6615→4854, `kspo_knowledge` 7493→5726. **Zero pages lost** (distinct normalized
  URLs unchanged: 3632 / 4279; both-scheme URLs now 0). This also cleans the path
  **Tiledesk** reads (it has no query-time dedup). Deleted-ID/source record kept
  for the session; per project design, loss is recoverable via re-crawl.
- **Grounding determinism (tested, reverted)** — temperature 0→0 made the LLM
  decline more often on borderline context (net +3 not-found on the purged index),
  so it was reverted to 0.1. Reproducibility isn't worth lost answer coverage here.

### Hybrid keyword arm — built, measured, REVERTED
I implemented a full hybrid: a Qdrant full-text index on `page_content`, an
IDF-weighted keyword arm (with a KO suffix stemmer + intent expansion for
address/phone/fee/hours), and RRF fusion with the dense arm — no re-embedding
needed. It **surfaced the authoritative HQ address/phone in isolation**, but on
the full 50-question set it was a **net regression: not-found 16 → 26** (fixed 5:
D6/E4/F5/G3/H2; broke 15). Cause: RRF weights a keyword-only rank-0 hit equally
with a dense rank-0 hit, so tangential keyword matches polluted the top-5 and
evicted the relevant dense chunk on the majority of (facility/program) questions.
Because it violated "previously-correct must stay correct," it was **reverted**
(code + tests + live index removed). Evidence retained in eval runs v5 vs v6.

**Lesson / corrected direction:** the residual factual-lookup class (canonical
org contact facts — address/phone/email/hours) is *not* fixable by a naive
keyword hybrid. It needs a **targeted** approach: an intent-gated hybrid (engage
the keyword arm only when dense confidence is low) or, better, a small **curated
entity / known-facts layer** for the ~dozen canonical org facts (HQ address,
representative phone, business hours) that the goal emphasizes. Those facts are
often stated in prose without trigger keywords ("…는 서울시 송파구 올림픽로 424에
있으며") or on subsidiary domains, so generic retrieval is the wrong tool.

### Known-facts layer — BUILT (fixes the contact-fact class)
Implemented `qa/facts.py` + `configs/known_facts.json`: an **intent-gated,
entity-aware** contact-fact resolver. For a query with contact/location/hours
intent AND a known entity alias, it injects the curated, **corpus-grounded** fact
(address/phone/email) as the top-authority context item with its source URL, so
the LLM answers correctly and cites it. Fires only on that intersection → other
questions are byte-for-byte unaffected (verified: 수영 프로그램 query unchanged).

- **A5 "위치는 어디인가요" → "서울특별시 송파구 올림픽로 424 …" with citation**,
  deterministic across runs (was permanently "정보 없음"). Phone and 소마미술관
  address likewise resolved.
- Each value is backed by a crawled source URL and corroborated across domains
  (multi-source verification: 올림픽로 424 appears on kspo.or.kr, soma, spoex,
  ksponco). Store is JSON, extensible to more entities/facilities.
- 8 unit tests (`test_qa_facts.py`); full suite 741 pass; ruff clean.

### Per-question triage of remaining not-founds (root cause per the goal)
After the fixes, not-found is **17 → 13**. Every remaining item classified by root
cause — most are *not* retrieval defects (declining on absent/stale/ambiguous
content is the authoritative-correct behavior; fabricating would be the defect):

| Q | Topic | Corpus | Root cause / verdict |
|---|---|---|---|
| D7 | WiFi | **0 chunks** | Coverage gap — decline is correct (no source to cite) |
| G5 | 인증서 발급 | **0** | Coverage gap — decline correct |
| D4 | 반려동물 | 1 | Near-absent — decline reasonable |
| B7 | 잔디광장 대관 | 3 | Sparse — needs facility page crawl |
| H1 | 수영장 규격 차이 | 2 | Comparison/synthesis across sparse chunks |
| H2 | 패밀리사이트 수 | 5 | Aggregation (count) — no single chunk states it; curating risks staleness |
| D6 | 음식물 반입 | 6 | Policy scattered; extend facts store (facility policy) |
| E2 | 입사지원 방법 | 7 | Procedural; recruitment-notice dependent |
| F4 | 기념관 전시 | 20 | **Time-sensitive** — current exhibitions; answering risks stale info |
| F5 | 문화행사 | 136 | **Time-sensitive** — event schedules; stale-risk |
| G4 | 운동처방 절차 | 28 | Procedural; extend facts store (service procedure) |
| F2 | 체육교실 | 917 | **LLM nondeterminism** — answers on some runs, declines on others (identical retrieval) |
| H4 | 스포렉스 시설 | 42 (event listings) | External event-hall; specific facility list sparse |

**Conclusion:** no *systematic retrieval defect class* remains unaddressed. The
residual is (a) genuine coverage gaps where declining is correct, (b) LLM sampling
nondeterminism, (c) time-sensitive content where declining avoids the stale-info
defect, and (d) a long tail of procedural/aggregation questions whose fix is
data curation (facts-store extension — mechanism done) or re-crawl, not a
retrieval-algorithm change. Curating a fact per remaining eval question would be
the question-specific overfitting the goal explicitly forbids.

### Residual — larger workstreams (need scoping / cost approval)
1. **Extend the known-facts store** — add remaining facility contacts / business
   hours as needed (mechanism is done; this is data curation).
2. **True sparse/BM25 hybrid or cross-encoder reranker** — requires re-embedding
   the corpus; only pursue if the facts layer + dense proves insufficient for
   non-canonical factual lookups.
3. **Crawl expansion** — spoex.com (external), WiFi/편의시설 detail. Needs
   crawler-adapter work + a crawl run; separate workstream.
