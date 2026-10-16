"""observability/email.py 단위 테스트 — aiosmtplib mock 기반."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from kspo_ingest.observability import email as email_mod


@pytest.fixture
def smtp_configured(monkeypatch):
    monkeypatch.setattr(email_mod.settings, "smtp_host", "smtp.test.local")
    monkeypatch.setattr(email_mod.settings, "smtp_port", 25)
    monkeypatch.setattr(email_mod.settings, "smtp_user", "")
    monkeypatch.setattr(email_mod.settings, "smtp_password", "")
    monkeypatch.setattr(email_mod.settings, "smtp_from", "from@test.local")
    monkeypatch.setattr(email_mod.settings, "smtp_to_recipients", "a@x.com,b@y.com")


@pytest.fixture
def fake_smtp(monkeypatch):
    """aiosmtplib.SMTP을 async context manager로 모킹."""
    smtp = MagicMock()
    smtp.send_message = AsyncMock()
    smtp.login = AsyncMock()

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=smtp)
    cm.__aexit__ = AsyncMock(return_value=None)

    constructor = MagicMock(return_value=cm)
    monkeypatch.setattr(email_mod.aiosmtplib, "SMTP", constructor)
    return smtp, constructor


@pytest.mark.asyncio
async def test_send_alert_email_success(smtp_configured, fake_smtp):
    smtp, _ = fake_smtp
    ok = await email_mod.send_alert_email(subject="test", body="hello")
    assert ok is True
    smtp.send_message.assert_awaited_once()
    smtp.login.assert_not_awaited()  # smtp_user 비어있어 login 안 함


@pytest.mark.asyncio
async def test_send_alert_email_with_auth(monkeypatch, smtp_configured, fake_smtp):
    monkeypatch.setattr(email_mod.settings, "smtp_user", "u")
    monkeypatch.setattr(email_mod.settings, "smtp_password", "p")
    smtp, _ = fake_smtp

    ok = await email_mod.send_alert_email(subject="t", body="b")
    assert ok is True
    smtp.login.assert_awaited_once_with("u", "p")


@pytest.mark.asyncio
async def test_smtp_not_configured_returns_false(monkeypatch):
    monkeypatch.setattr(email_mod.settings, "smtp_host", "")
    monkeypatch.setattr(email_mod.settings, "smtp_to_recipients", "")
    ok = await email_mod.send_alert_email(subject="t", body="b")
    assert ok is False


@pytest.mark.asyncio
async def test_smtp_configured_but_no_recipients_returns_false(monkeypatch):
    monkeypatch.setattr(email_mod.settings, "smtp_host", "smtp.test.local")
    monkeypatch.setattr(email_mod.settings, "smtp_to_recipients", "  ,  ")  # 빈 값들
    ok = await email_mod.send_alert_email(subject="t", body="b")
    assert ok is False


@pytest.mark.asyncio
async def test_smtp_send_failure_does_not_raise(smtp_configured, monkeypatch):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=ConnectionRefusedError("no smtp"))
    cm.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(email_mod.aiosmtplib, "SMTP", MagicMock(return_value=cm))

    ok = await email_mod.send_alert_email(subject="t", body="b")
    assert ok is False  # 예외 raise 없이 False 반환


@pytest.mark.asyncio
async def test_recipients_comma_split_correctly(smtp_configured, fake_smtp):
    smtp, _ = fake_smtp
    await email_mod.send_alert_email(subject="t", body="b")
    # send_message 호출 시 EmailMessage의 To 헤더에 두 주소 모두
    msg = smtp.send_message.call_args[0][0]
    assert "a@x.com" in msg["To"]
    assert "b@y.com" in msg["To"]
