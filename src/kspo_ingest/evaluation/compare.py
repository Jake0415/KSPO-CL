"""Multi-provider quality comparison for LLM refinement.

Runs the same test cases through multiple providers and collects
structured results for comparison reporting.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from kspo_ingest.observability.logger import get_logger
from kspo_ingest.refine.cost import calc_cost_usd
from kspo_ingest.refine.provider import get_provider

log = get_logger("evaluation", "compare")


@dataclass
class CaseResult:
    title: str
    refined_text: str
    is_meaningful: bool
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: float
    dropped: bool


@dataclass
class ComparisonResult:
    provider_name: str
    model: str
    cases: list[CaseResult] = field(default_factory=list)
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    meaningful_rate: float = 0.0


async def refine_with_provider(
    provider_name: str, *, title: str, body_text: str
) -> CaseResult:
    """Refine a single page with a specific provider."""
    from kspo_ingest.refine.prompts import SYSTEM_PROMPT, build_user_prompt
    from kspo_ingest.refine.schema import REFINER_JSON_SCHEMA, RefinerOutput

    provider = get_provider(provider_name)

    t0 = time.monotonic()
    response = await provider.chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(title, body_text)},
        ],
        response_format={"type": "json_schema", "json_schema": REFINER_JSON_SCHEMA},
        temperature=0.0,
    )
    latency_ms = (time.monotonic() - t0) * 1000

    raw = response.choices[0].message.content or ""
    refined = RefinerOutput.model_validate_json(raw)
    usage = response.usage

    cost = float(calc_cost_usd(
        model=provider.model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
    ))

    return CaseResult(
        title=title or "",
        refined_text=refined.refined_text,
        is_meaningful=refined.is_meaningful,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cost_usd=cost,
        latency_ms=latency_ms,
        dropped=False,
    )


async def compare_providers(
    *,
    test_cases: list[dict],
    provider_names: list[str],
) -> list[ComparisonResult]:
    """Run test cases through multiple providers and return comparison results."""
    results: list[ComparisonResult] = []

    for pname in provider_names:
        provider = get_provider(pname)
        comp = ComparisonResult(provider_name=pname, model=provider.model)

        for case in test_cases:
            try:
                cr = await refine_with_provider(
                    pname, title=case["title"], body_text=case["body_text"]
                )
                comp.cases.append(cr)
            except Exception as e:
                log.bind(
                    event="compare_error",
                    provider=pname,
                    title=case.get("title"),
                    error=str(e),
                ).warning("provider comparison failed")
                comp.cases.append(
                    CaseResult(
                        title=case.get("title", ""),
                        refined_text="",
                        is_meaningful=False,
                        prompt_tokens=0,
                        completion_tokens=0,
                        cost_usd=0.0,
                        latency_ms=0.0,
                        dropped=True,
                    )
                )

        if comp.cases:
            comp.total_cost_usd = sum(c.cost_usd for c in comp.cases)
            comp.avg_latency_ms = sum(c.latency_ms for c in comp.cases) / len(comp.cases)
            meaningful = [c for c in comp.cases if c.is_meaningful and not c.dropped]
            comp.meaningful_rate = len(meaningful) / len(comp.cases)

        results.append(comp)

    return results
