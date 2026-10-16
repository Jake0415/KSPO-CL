from __future__ import annotations

from dataclasses import dataclass

from kspo_ingest.observability.logger import get_logger
from kspo_ingest.refine import pre_rules
from kspo_ingest.refine.cost import TokenUsage
from kspo_ingest.refine.prompts import SYSTEM_PROMPT, build_user_prompt
from kspo_ingest.refine.provider import get_provider
from kspo_ingest.refine.schema import REFINER_JSON_SCHEMA, RefinerOutput
from kspo_ingest.settings import settings

log = get_logger("refine", "refiner")


@dataclass
class RefineResult:
    drop: bool
    drop_reason: str | None
    refined: RefinerOutput | None
    usage: TokenUsage | None
    model: str


async def refine_page(*, title: str | None, body_text: str) -> RefineResult:
    """사전 룰 → OpenAI structured output → 결과 반환.

    호출 측 책임:
      - usage가 있으면 cost.record_llm_usage(session, ...)로 PG 기록
      - drop=True면 pages.status='DROPPED', drop_reason 저장
      - 의미 판별로 제외하지 않으며 caller가 원문과 검색 보강 내용을 보존
    """
    pre = pre_rules.check(body_text, title, ko_ratio_threshold=settings.ko_ratio_threshold)
    if pre.drop:
        log.bind(event="refine_drop", reason=pre.reason, body_len=len(body_text)).info(
            "pre-rule drop"
        )
        return RefineResult(
            drop=True,
            drop_reason=pre.reason,
            refined=None,
            usage=None,
            model=get_provider().model,
        )

    provider = get_provider()
    model = provider.model

    response = await provider.chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(title, body_text)},
        ],
        response_format={"type": "json_schema", "json_schema": REFINER_JSON_SCHEMA},
        temperature=0.0,
    )

    raw = response.choices[0].message.content or ""
    refined = RefinerOutput.model_validate_json(raw)
    usage = TokenUsage(
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        total_tokens=response.usage.total_tokens,
    )
    log.bind(
        event="refine_ok",
        model=model,
        prompt=usage.prompt_tokens,
        completion=usage.completion_tokens,
        is_meaningful=refined.is_meaningful,
    ).info("refine ok")

    return RefineResult(
        drop=False,
        drop_reason=None,
        refined=refined,
        usage=usage,
        model=model,
    )
