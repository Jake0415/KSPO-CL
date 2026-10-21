"""LLM provider abstraction — factory returns provider by name.

All providers use the OpenAI SDK. Gemini is accessed via OpenAI-compatible endpoint.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from openai import AsyncOpenAI
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from kspo_ingest.refine.openai_client import RETRYABLE_EXC
from kspo_ingest.settings import settings


@dataclass
class LlmProvider:
    name: str
    client: AsyncOpenAI
    model: str

    async def chat_completion(
        self,
        *,
        messages: list[dict],
        response_format: dict | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
    ):
        """Call chat completions with retry.

        ``seed`` requests best-effort reproducible sampling (with temperature=0)
        so the same prompt yields the same answer run-to-run — LLM inference is
        otherwise non-deterministic even at temperature 0.
        """
        async with asyncio.timeout(settings.refine_total_timeout_seconds):
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(settings.refine_max_attempts),
                wait=wait_exponential(multiplier=1, min=1, max=4),
                retry=retry_if_exception_type(RETRYABLE_EXC),
                reraise=True,
            ):
                with attempt:
                    kwargs: dict = {
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                    }
                    if seed is not None:
                        kwargs["seed"] = seed
                    if response_format is not None:
                        kwargs["response_format"] = response_format
                    return await self.client.chat.completions.create(**kwargs)
        raise RuntimeError("unreachable")  # pragma: no cover


_providers: dict[str, LlmProvider] = {}


def get_provider(name: str | None = None) -> LlmProvider:
    """Get or create a named LLM provider."""
    provider_name = name or settings.llm_provider

    if provider_name in _providers:
        return _providers[provider_name]

    if provider_name == "openai":
        provider = LlmProvider(
            name="openai",
            client=AsyncOpenAI(
                api_key=settings.openai_api_key,
                timeout=settings.refine_request_timeout_seconds,
                max_retries=0,
            ),
            model=settings.openai_refine_model,
        )
    elif provider_name == "gemini":
        provider = LlmProvider(
            name="gemini",
            client=AsyncOpenAI(
                api_key=settings.gemini_api_key,
                base_url=settings.gemini_base_url,
                timeout=settings.refine_request_timeout_seconds,
                max_retries=0,
            ),
            model=settings.gemini_model,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")

    _providers[provider_name] = provider
    return provider


def reset_providers() -> None:
    """Clear cached providers (for testing)."""
    _providers.clear()
