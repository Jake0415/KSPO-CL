"""SMTP 알림 발신 — KSPO 사내 SMTP 가정 (인증 없거나 단순 인증 모두 지원).

cron의 의무적 동작이 아니므로 SMTP 미설정/실패 시 cron task를 실패시키지 않는다.
WARN 로그만 남기고 False 반환.
"""
from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib

from kspo_ingest.observability.logger import get_logger
from kspo_ingest.settings import settings

log = get_logger("observability", "email")


async def send_alert_email(*, subject: str, body: str) -> bool:
    """알림 이메일 발신. 성공 True / 미설정·실패 False."""
    if not settings.smtp_host or not settings.smtp_to_recipients:
        log.bind(event="smtp_not_configured").warning("alert skipped — SMTP missing")
        return False

    recipients = [r.strip() for r in settings.smtp_to_recipients.split(",") if r.strip()]
    if not recipients:
        log.bind(event="smtp_no_recipients").warning("alert skipped — no recipients")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or "kspo-ingest@localhost"
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    try:
        async with aiosmtplib.SMTP(
            hostname=settings.smtp_host, port=settings.smtp_port
        ) as smtp:
            if settings.smtp_user:
                await smtp.login(settings.smtp_user, settings.smtp_password)
            await smtp.send_message(msg)
        log.bind(
            event="alert_email_sent",
            subject=subject,
            recipients=len(recipients),
        ).info("alert email sent")
        return True
    except Exception as exc:  # noqa: BLE001
        log.bind(
            event="alert_email_failed",
            error=type(exc).__name__,
        ).warning(str(exc))
        return False
