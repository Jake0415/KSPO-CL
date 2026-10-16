from __future__ import annotations

import pytest

from kspo_ingest.refine.provider import LlmProvider, get_provider, reset_providers


@pytest.fixture(autouse=True)
def _clean_providers(monkeypatch):
    """Reset cached providers and set dummy API keys."""
    monkeypatch.setattr("kspo_ingest.settings.settings.openai_api_key", "sk-test")
    monkeypatch.setattr("kspo_ingest.settings.settings.gemini_api_key", "gem-test")
    reset_providers()
    yield
    reset_providers()


def test_get_provider_openai():
    provider = get_provider("openai")
    assert isinstance(provider, LlmProvider)
    assert provider.name == "openai"


def test_get_provider_gemini():
    provider = get_provider("gemini")
    assert isinstance(provider, LlmProvider)
    assert provider.name == "gemini"


def test_get_provider_default_is_openai():
    provider = get_provider()
    assert provider.name == "openai"


def test_get_provider_invalid_raises():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_provider("invalid_provider")


def test_get_provider_caches():
    p1 = get_provider("openai")
    p2 = get_provider("openai")
    assert p1 is p2


def test_reset_clears_cache():
    p1 = get_provider("openai")
    reset_providers()
    p2 = get_provider("openai")
    assert p1 is not p2
