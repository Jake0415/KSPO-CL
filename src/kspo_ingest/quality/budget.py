"""Budget-aware pipeline test — $5 예산 내 전체 파이프라인 검증.

모드:
- dry_run: LLM 호출 없이 토큰 수만 추정
- mock: 가짜 LLM 응답으로 파이프라인 검증
- sample: 대표 샘플만 실제 LLM 호출
- budget: 예산 한도 내에서 자동 범위 조정
- live: 실제 LLM 호출 (전체)

핵심:
- content_hash 기반 응답 캐시 — 동일 문서 재호출 방지
- 토큰/비용 추적 — 모든 호출 기록
- 대표 샘플 자동 선정 — 문서 유형별 커버리지 극대화
"""
from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from kspo_ingest.chunk.tokens import count_tokens
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.refine.cost import calc_cost_usd
from kspo_ingest.refine.prompts import SYSTEM_PROMPT, build_user_prompt

log = get_logger("quality", "budget")


class RunMode(StrEnum):
    DRY_RUN = "dry_run"   # 토큰 추정만, LLM 호출 없음
    MOCK = "mock"         # 가짜 응답으로 파이프라인 검증
    SAMPLE = "sample"     # 대표 샘플만 실제 호출
    BUDGET = "budget"     # 예산 한도 내 자동 조정
    LIVE = "live"         # 전체 실제 호출


@dataclass
class CallRecord:
    """LLM 호출 1건의 기록."""
    url: str
    content_hash: str
    purpose: str           # "refine" | "embedding"
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    cached: bool
    mock: bool
    elapsed_ms: int = 0
    success: bool = True
    error: str = ""


@dataclass
class BudgetReport:
    """전체 테스트 비용 리포트."""
    mode: str
    budget_usd: float
    total_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cost_usd: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    mock_calls: int = 0
    live_calls: int = 0
    documents_tested: int = 0
    documents_skipped: int = 0
    calls: list[CallRecord] = field(default_factory=list)
    site_costs: dict[str, float] = field(default_factory=dict)

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0

    @property
    def budget_remaining(self) -> float:
        return self.budget_usd - self.total_cost_usd

    @property
    def avg_cost_per_doc(self) -> float:
        if self.documents_tested == 0:
            return 0.0
        return self.total_cost_usd / self.documents_tested

    def add_call(self, record: CallRecord) -> None:
        self.calls.append(record)
        self.total_calls += 1
        self.total_prompt_tokens += record.prompt_tokens
        self.total_completion_tokens += record.completion_tokens
        self.total_cost_usd += record.cost_usd
        if record.cached:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
        if record.mock:
            self.mock_calls += 1
        else:
            self.live_calls += 1


class ResponseCache:
    """content_hash 기반 LLM 응답 캐시.

    동일 문서 재호출 방지. 디스크 영속화 지원.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._memory: dict[str, dict[str, Any]] = {}
        self._cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
            self._load_disk()

    def _load_disk(self) -> None:
        if not self._cache_dir:
            return
        cache_file = self._cache_dir / "llm_cache.json"
        if cache_file.exists():
            with contextlib.suppress(Exception):
                self._memory = json.loads(cache_file.read_text("utf-8"))

    def _save_disk(self) -> None:
        if not self._cache_dir:
            return
        cache_file = self._cache_dir / "llm_cache.json"
        cache_file.write_text(json.dumps(self._memory, ensure_ascii=False), "utf-8")

    def get(self, content_hash: str, purpose: str) -> dict[str, Any] | None:
        key = f"{purpose}:{content_hash}"
        return self._memory.get(key)

    def put(self, content_hash: str, purpose: str, response: dict[str, Any]) -> None:
        key = f"{purpose}:{content_hash}"
        self._memory[key] = response
        self._save_disk()

    @property
    def size(self) -> int:
        return len(self._memory)


def estimate_refine_tokens(title: str | None, body_text: str) -> tuple[int, int]:
    """Refine 호출의 예상 토큰 수 (prompt, completion)."""
    system_tokens = count_tokens(SYSTEM_PROMPT)
    user_prompt = build_user_prompt(title, body_text)
    user_tokens = count_tokens(user_prompt)
    prompt_total = system_tokens + user_tokens

    # 응답 예상: refined_text(본문의 ~80%) + summary(100t) + keywords(50t) + JSON 오버헤드(30t)
    est_completion = min(int(count_tokens(body_text) * 0.8) + 180, 4000)

    return prompt_total, est_completion


def estimate_embed_tokens(chunks: list[str]) -> int:
    """Embedding 호출의 예상 토큰 수."""
    return sum(count_tokens(c) for c in chunks)


def estimate_page_cost(
    title: str | None,
    body_text: str,
    *,
    refine_model: str = "gpt-5.4-mini",
    embed_model: str = "text-embedding-3-large",
    chunk_count: int = 1,
    avg_chunk_tokens: int = 700,
) -> dict[str, float]:
    """페이지 1건의 예상 비용."""
    ref_prompt, ref_completion = estimate_refine_tokens(title, body_text)
    ref_cost = float(calc_cost_usd(refine_model, ref_prompt, ref_completion))

    embed_tokens = chunk_count * avg_chunk_tokens
    embed_cost = float(calc_cost_usd(embed_model, embed_tokens, 0))

    return {
        "refine_prompt_tokens": ref_prompt,
        "refine_completion_tokens": ref_completion,
        "refine_cost_usd": ref_cost,
        "embed_tokens": embed_tokens,
        "embed_cost_usd": embed_cost,
        "total_cost_usd": ref_cost + embed_cost,
    }


MOCK_REFINE_RESPONSE = {
    "refined_text": "[MOCK] 파이프라인 검증용 정제 텍스트입니다.",
    "is_meaningful": True,
    "summary": "[MOCK] 파이프라인 검증용 요약입니다.",
    "keywords": ["파이프라인", "검증", "테스트"],
}


def format_budget_report(report: BudgetReport) -> str:
    """비용 리포트를 텍스트로 포맷."""
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("  Pipeline Budget Report")
    lines.append("=" * 60)
    lines.append(f"  Mode           : {report.mode}")
    lines.append(f"  Budget         : ${report.budget_usd:.2f}")
    lines.append(f"  Total Cost     : ${report.total_cost_usd:.6f}")
    lines.append(f"  Remaining      : ${report.budget_remaining:.6f}")
    lines.append(
        f"  Documents      : {report.documents_tested} tested, {report.documents_skipped} skipped"
    )
    lines.append("")
    lines.append(f"  Total Calls    : {report.total_calls}")
    lines.append(f"  Live Calls     : {report.live_calls}")
    lines.append(f"  Mock Calls     : {report.mock_calls}")
    lines.append(f"  Cache Hits     : {report.cache_hits} ({report.cache_hit_rate:.0%})")
    lines.append("")
    lines.append(f"  Prompt Tokens  : {report.total_prompt_tokens:,}")
    lines.append(f"  Complet Tokens : {report.total_completion_tokens:,}")
    lines.append(f"  Avg Cost/Doc   : ${report.avg_cost_per_doc:.6f}")
    lines.append("")

    if report.site_costs:
        lines.append("  Cost by Site:")
        for host, cost in sorted(report.site_costs.items()):
            lines.append(f"    {host:<30} ${cost:.6f}")
    lines.append("")

    # 문서별 상세
    if report.calls:
        lines.append("  Call Details:")
        for c in report.calls[:20]:
            cached_str = "CACHE" if c.cached else ("MOCK" if c.mock else "LIVE")
            status = "OK" if c.success else "FAIL"
            lines.append(
                f"    [{cached_str}] {c.purpose:<9} {c.prompt_tokens:>6}pt "
                f"${c.cost_usd:.6f} {status} {c.url[:50]}"
            )
        if len(report.calls) > 20:
            lines.append(f"    ... and {len(report.calls) - 20} more")

    lines.append("=" * 60)
    return "\n".join(lines)
