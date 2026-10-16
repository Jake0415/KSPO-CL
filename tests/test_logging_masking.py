"""observability/masking.py 단위 테스트 — 시크릿 패턴 8종 + 길이 제한."""
from __future__ import annotations

from kspo_ingest.observability.masking import mask


def test_openai_key_masked():
    s = "calling sk-abcd1234EFGH5678ijkl with model"
    out = mask(s)
    assert "sk-abcd1234" not in out
    assert "***" in out


def test_openai_project_key_masked():
    s = "key=sk-proj-jSvBgOe5ppzqQY2yQOM25bGsWtixbe8tRbt2i0JLYHl-D2H9NiMZq8SKnAHN"
    out = mask(s)
    assert "sk-proj-jSvBg" not in out
    assert "***" in out


def test_bearer_token_masked():
    s = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def"
    out = mask(s)
    assert "eyJhbGciOi" not in out
    assert "Bearer ***" in out


def test_basic_auth_masked():
    s = "Authorization: Basic YWRtaW46c2VjcmV0cGFzc3dvcmQxMjM="
    out = mask(s)
    assert "YWRtaW46c2VjcmV0" not in out
    assert "Basic ***" in out


def test_postgres_dsn_password_masked_host_preserved():
    s = "postgresql+asyncpg://kspo:supersecret@postgres:5432/kspo_ingest"
    out = mask(s)
    assert "supersecret" not in out
    assert "postgres:5432" in out  # host:port 보존
    assert "kspo:***@" in out


def test_redis_url_password_masked():
    s = "redis://default:redispass@redis:6379/0"
    out = mask(s)
    assert "redispass" not in out
    assert "redis:6379" in out


def test_session_cookie_masked():
    s = "Cookie: session=abcdef1234567890_signedvalue"
    out = mask(s)
    assert "abcdef1234567890" not in out
    assert "session=***" in out


def test_bcrypt_hash_masked():
    s = "$2b$12$ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123"
    out = mask(s)
    assert "ABCDEFGHIJKL" not in out
    assert "***" in out


def test_truncates_when_exceeding_max_len():
    s = "a" * 9000
    out = mask(s, max_len=8000)
    assert len(out) <= 8000 + len("...truncated...")
    assert out.endswith("...truncated...")


def test_normal_message_unchanged():
    s = "fetch_ok page_id=42 elapsed_ms=120"
    assert mask(s) == s


def test_non_string_input_returned_as_is():
    assert mask(None) is None  # type: ignore[arg-type]
    assert mask(42) == 42  # type: ignore[arg-type]


def test_empty_string_unchanged():
    assert mask("") == ""
