from __future__ import annotations

from kspo_ingest.settings import Settings


def _make_settings(**overrides) -> Settings:
    base = {
        "admin_password_bcrypt": "x",
        "session_secret": "y",
        "postgres_user": "u",
        "postgres_password": "p",
    }
    base.update(overrides)
    return Settings(**base)


def test_default_no_proxy_includes_internal_hosts():
    s = _make_settings()
    for host in ("localhost", "127.0.0.1", "postgres", "redis", "qdrant", "host.docker.internal"):
        assert host in s.no_proxy


def test_default_qdrant_url_is_dev_container():
    s = _make_settings()
    assert s.qdrant_url == "http://qdrant:6333"


def test_default_monthly_budget_is_150k():
    s = _make_settings()
    assert s.openai_monthly_budget_krw == 150_000


def test_proxy_env_vars_default_empty():
    s = _make_settings()
    assert s.https_proxy == ""
    assert s.http_proxy == ""


def test_proxy_env_vars_propagate():
    s = _make_settings(https_proxy="http://proxy.kspo.local:8080")
    assert s.https_proxy == "http://proxy.kspo.local:8080"


def test_default_models():
    s = _make_settings()
    assert s.openai_refine_model == "gpt-5.4-mini"
    assert s.openai_embed_model == "text-embedding-3-large"


def test_default_namespace_and_version():
    s = _make_settings()
    assert s.kb_namespace == "kspo"
    assert s.embedding_version == 1
