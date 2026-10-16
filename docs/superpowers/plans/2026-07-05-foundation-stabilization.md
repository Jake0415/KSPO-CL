# Foundation Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all test failures, install missing test dependencies, resolve pre-existing bugs, and wire `posted_at` propagation — achieving CI green with 0 failures.

**Architecture:** Three independent fix categories: (1) test infrastructure (missing deps + 204 status), (2) pre-existing logic bugs in hash/encoding, (3) `posted_at` data flow gap where `clean_page` saves `page.posted_at` to DB but `enqueue_seeds`/`run_incremental` hardcode `None` in `ScorerInput`. All fixes are surgical, no architectural changes.

**Tech Stack:** Python 3.12, pytest, FastAPI, regex, charset-normalizer

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `pyproject.toml` | No change | Test deps already declared under `[project.optional-dependencies] test` |
| `src/kspo_ingest/api/routers/qa_logs.py` | Modify | Fix 204 response with body |
| `src/kspo_ingest/clean/hash.py` | Modify | Fix regex for view count and today date stripping |
| `src/kspo_ingest/clean/encoding.py` | Modify | Accept `ascii` as valid UTF-8 superset |
| `src/kspo_ingest/tasks/pipeline/enqueue_seeds.py` | Modify | Read `page.posted_at` from DB |
| `src/kspo_ingest/tasks/pipeline/run_incremental.py` | Modify | Read `page.posted_at` from DB |
| `tests/test_clean_hash.py` | No change | Existing tests become pass |
| `tests/test_encoding.py` | No change | Existing test becomes pass |
| `tests/test_enqueue_seeds_bfs.py` | Modify | Verify posted_at propagation |
| `tests/test_incremental.py` | Modify | Verify posted_at propagation |

---

### Task 1: Install Test Dependencies

**Files:**
- No code changes — pip install only

- [ ] **Step 1: Install test extras**

```bash
pip install -e ".[test]"
```

- [ ] **Step 2: Verify previously-broken imports resolve**

Run: `python -c "import respx; import fakeredis.aioredis; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Verify previously-uncollectable test files now collect**

Run: `python -m pytest tests/test_frontier.py tests/test_checkpoint.py tests/test_robots.py --co -q 2>&1 | tail -3`
Expected: Shows test count (not ImportError)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: install test extras (respx, fakeredis)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Fix 204 Status Code Response Body

**Files:**
- Modify: `src/kspo_ingest/api/routers/qa_logs.py:70`

FastAPI 0.115+ enforces that `status_code=204` must not have a response body. The `update_satisfaction` endpoint returns `None` implicitly, which FastAPI interprets as a body. Fix: change to 200 or use `Response(status_code=204)`.

- [ ] **Step 1: Write a targeted test**

```python
# tests/test_qa_logs_satisfaction.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def mock_qa_log():
    log = MagicMock()
    log.satisfaction = None
    return log


@pytest.fixture
async def client(mock_qa_log):
    from kspo_ingest.api.main import create_app

    app = create_app()

    async def mock_get(model, pk):
        from kspo_ingest.db.models import QaLog
        if model is QaLog:
            return mock_qa_log
        return None

    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=mock_get)
    mock_session.commit = AsyncMock()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_session_factory():
        yield mock_session

    from kspo_ingest.api import deps
    app.dependency_overrides[deps.get_session] = lambda: mock_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_satisfaction_returns_no_content(client, mock_qa_log):
    resp = await client.post("/api/qa-logs/1/satisfaction", json={"satisfaction": 4})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run to verify it fails (204 body assertion during app construction)**

Run: `python -m pytest tests/test_qa_logs_satisfaction.py -v 2>&1 | tail -10`
Expected: FAIL or ERROR with "Status code 204 must not have a response body"

- [ ] **Step 3: Fix the endpoint — change 204 to 200**

In `src/kspo_ingest/api/routers/qa_logs.py`, change line 70:

```python
# Before:
@router.post("/{log_id}/satisfaction", status_code=status.HTTP_204_NO_CONTENT)

# After:
@router.post("/{log_id}/satisfaction", status_code=status.HTTP_200_OK)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_qa_logs_satisfaction.py -v`
Expected: PASS

- [ ] **Step 5: Verify previously-broken test files now collect**

Run: `python -m pytest tests/test_auth_lockout_integration.py tests/test_files_endpoint.py --co -q 2>&1 | tail -3`
Expected: Shows test count, no AssertionError

- [ ] **Step 6: Commit**

```bash
git add src/kspo_ingest/api/routers/qa_logs.py tests/test_qa_logs_satisfaction.py
git commit -m "fix: change qa-logs satisfaction endpoint from 204 to 200

FastAPI 0.115+ enforces 204 must not have response body.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Fix Hash Normalization — View Count Regex

**Files:**
- Modify: `src/kspo_ingest/clean/hash.py:7-8`
- Test: `tests/test_clean_hash.py` (existing, no changes)

The regex `_RE_VIEW_COUNT` fails because the pattern `조회수\s*[:：]?\s*\d[,\d]*` requires the digits to be directly adjacent. The test input `조회수: 123` has a colon and space. Also `_RE_TODAY` uses a non-greedy match that doesn't consume the full date string.

- [ ] **Step 1: Run the failing tests to understand current behavior**

Run: `python -m pytest tests/test_clean_hash.py::test_view_count_stripped tests/test_clean_hash.py::test_today_date_stripped -v --tb=short`
Expected: 2 FAIL

- [ ] **Step 2: Fix the regex patterns**

In `src/kspo_ingest/clean/hash.py`, replace the regex definitions:

```python
# Before:
_RE_VIEW_COUNT = re.compile(r"조회수\s*[:：]?\s*\d[,\d]*")
_RE_TODAY = re.compile(r"오늘\s*날짜\s*[:：]?.*?(?=\s|$)")

# After:
_RE_VIEW_COUNT = re.compile(r"조회수\s*[:：]?\s*[\d,]+")
_RE_TODAY = re.compile(r"오늘\s*날짜\s*[:：]?\s*\S*")
```

Changes:
- `_RE_VIEW_COUNT`: `\d[,\d]*` -> `[\d,]+` to match digits with commas in any order after optional whitespace
- `_RE_TODAY`: `.*?(?=\s|$)` -> `\s*\S*` to consume optional whitespace then the date token (non-greedy lookahead was stopping too early)

- [ ] **Step 3: Run tests to verify both pass**

Run: `python -m pytest tests/test_clean_hash.py -v`
Expected: 6 PASS, 0 FAIL

- [ ] **Step 4: Commit**

```bash
git add src/kspo_ingest/clean/hash.py
git commit -m "fix: hash normalization regex for view count and today date

View count regex didn't match '조회수: 123' format.
Today date regex used non-greedy lookahead that stopped too early.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Fix Encoding Detection — ASCII Fallback

**Files:**
- Modify: `src/kspo_ingest/clean/encoding.py:52-59`
- Test: `tests/test_encoding.py` (existing, no changes)

`charset_normalizer` correctly detects `b"plain ascii"` as `ascii` encoding. The test expects `utf-8` because ASCII is a valid subset of UTF-8. Fix: when charset_normalizer returns `ascii`, map it to `utf-8` since all ASCII bytes are valid UTF-8.

- [ ] **Step 1: Run the failing test**

Run: `python -m pytest tests/test_encoding.py::test_fallback_to_utf8_when_all_fail -v --tb=short`
Expected: FAIL — `assert 'ascii' == 'utf-8'`

- [ ] **Step 2: Fix encoding detection to normalize ascii to utf-8**

In `src/kspo_ingest/clean/encoding.py`, after the charset_normalizer block, add normalization:

```python
    # 4) charset_normalizer
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is not None and best.encoding:
            enc = best.encoding
            # ASCII is a subset of UTF-8; normalize for consistency
            if enc.lower() == "ascii":
                enc = "utf-8"
            if _try_decode(raw, enc):
                return enc
    except Exception:
        pass
```

- [ ] **Step 3: Run test to verify it passes**

Run: `python -m pytest tests/test_encoding.py -v`
Expected: 7 PASS, 0 FAIL

- [ ] **Step 4: Commit**

```bash
git add src/kspo_ingest/clean/encoding.py
git commit -m "fix: normalize ascii detection to utf-8 in encoding detector

charset_normalizer correctly identifies plain ASCII but we normalize
to utf-8 since ASCII is a strict subset and utf-8 is our canonical encoding.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Wire posted_at Propagation in Orchestrators

**Files:**
- Modify: `src/kspo_ingest/tasks/pipeline/enqueue_seeds.py:93-106`
- Modify: `src/kspo_ingest/tasks/pipeline/run_incremental.py:113-127`
- Test: `tests/test_enqueue_seeds_bfs.py`
- Test: `tests/test_incremental.py`

`clean_page` already writes `page.posted_at` to DB (line 90-92 of `clean_page.py`). But both orchestrators hardcode `posted_at=None` in `ScorerInput`. Fix: read `page.posted_at` from the DB session that already loads the domain.

- [ ] **Step 1: Write a test for enqueue_seeds posted_at propagation**

First, read the existing test to understand its mock structure:

Run: `head -50 tests/test_enqueue_seeds_bfs.py`

Then add a test that verifies `score_document` receives `posted_at` from the page. The approach depends on the test's mock structure — typically we can patch `score_document` and assert the input.

- [ ] **Step 2: Fix enqueue_seeds.py — read posted_at from page**

In `src/kspo_ingest/tasks/pipeline/enqueue_seeds.py`, the domain session block (lines 93-95) already opens a session and gets the domain. Read the page's posted_at there too:

```python
            # Before (lines 93-106):
            async with session_factory() as s:
                domain = await s.get(Domain, domain_id)
                domain_host = domain.host if domain else ""

            score = score_document(ScorerInput(
                title=cleaned["title"],
                body_text=cleaned["body_text"],
                extraction_method=cleaned.get("method", "heuristic"),
                posted_at=None,  # Page.posted_at — clean에서 추출됨
                ...
            ))

            # After:
            async with session_factory() as s:
                domain = await s.get(Domain, domain_id)
                domain_host = domain.host if domain else ""
                page_row = await s.get(Page, page_id)
                page_posted_at = getattr(page_row, "posted_at", None) if page_row else None

            score = score_document(ScorerInput(
                title=cleaned["title"],
                body_text=cleaned["body_text"],
                extraction_method=cleaned.get("method", "heuristic"),
                posted_at=page_posted_at,
                ...
            ))
```

- [ ] **Step 3: Fix run_incremental.py — same pattern**

In `src/kspo_ingest/tasks/pipeline/run_incremental.py`, the same block (lines 113-116):

```python
            # Before:
            async with session_factory() as s:
                domain = await s.get(Domain, domain_id)
                domain_host = domain.host if domain else ""

            score = score_document(ScorerInput(
                ...
                posted_at=None,
                ...
            ))

            # After:
            async with session_factory() as s:
                domain = await s.get(Domain, domain_id)
                domain_host = domain.host if domain else ""
                page_row = await s.get(Page, page_id)
                page_posted_at = getattr(page_row, "posted_at", None) if page_row else None

            score = score_document(ScorerInput(
                ...
                posted_at=page_posted_at,
                ...
            ))
```

- [ ] **Step 4: Add Page import to run_incremental.py if not already present**

Check: `Page` is already imported in `run_incremental.py` (line 19: `from kspo_ingest.db.models import Domain, Page`). Same for `enqueue_seeds.py` (line 16). No import changes needed.

- [ ] **Step 5: Run existing tests to verify no regressions**

Run: `python -m pytest tests/test_enqueue_seeds_bfs.py tests/test_incremental.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/kspo_ingest/tasks/pipeline/enqueue_seeds.py src/kspo_ingest/tasks/pipeline/run_incremental.py
git commit -m "fix: propagate page.posted_at to ScorerInput in orchestrators

clean_page saves posted_at to DB but enqueue_seeds and run_incremental
hardcoded None. Now reads page.posted_at from DB for accurate freshness scoring.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Full Regression Test

**Files:**
- No changes — verification only

- [ ] **Step 1: Run the full test suite**

```bash
python -m pytest tests/ --ignore=tests/e2e --tb=short -q 2>&1 | tail -5
```

Expected: `N passed, 0 failed, M skipped` — **zero failures**.

The previously-broken test files (test_auth_lockout_integration, test_files_endpoint, test_auth, test_health) should now collect and run since the 204 issue is fixed.

- [ ] **Step 2: Run ruff to verify code quality**

```bash
python -m ruff check src/kspo_ingest/ --select F
```

Expected: `All checks passed!`

- [ ] **Step 3: Record final test count**

```bash
python -m pytest tests/ --ignore=tests/e2e --tb=no -q 2>&1 | tail -1
```

Record the exact `N passed, 0 failed, M skipped` line for the project status.

- [ ] **Step 4: Final commit (if any cleanup needed)**

If everything passes, no commit needed. If minor fixes were needed, commit them.
