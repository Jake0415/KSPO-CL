"""ARQ cron — 분 단위 월 비용 80% 임계 검사 + 알림 발신."""
from __future__ import annotations

from kspo_ingest.observability.cost_monitor import check_budget_threshold
from kspo_ingest.observability.email import send_alert_email
from kspo_ingest.observability.logger import get_logger

log = get_logger("cron", "alerts")


async def check_budget_alerts(ctx: dict) -> dict:
    """이번 달 누계가 한도 80%에 도달하면 같은 달 1회만 SMTP 발신.

    Returns: {sent: bool, used_pct: float}.
    SMTP 미설정/실패는 WARN 로그만 — cron task 자체는 항상 성공으로 종료.
    """
    session_factory = ctx["session_factory"]
    redis = ctx.get("redis")

    async with session_factory() as s:
        decision = await check_budget_threshold(s, redis=redis)

    sent = False
    if decision.crossed_threshold:
        body = (
            "이번 달 OpenAI 누계 비용이 한도의 80%에 도달했습니다.\n"
            f"누계: {decision.cost_krw:,}원 / 한도: {decision.budget_krw:,}원 "
            f"({decision.used_pct:.1f}%)\n\n"
            "런북 B.2.B 참조: docs/runbook/B_openai_failure.md"
        )
        sent = await send_alert_email(
            subject=(
                f"[kspo-ingest] OpenAI 월 누계 80% 도달 ({decision.used_pct:.1f}%)"
            ),
            body=body,
        )
        log.bind(
            event="budget_alert_sent",
            cost_krw=str(decision.cost_krw),
            used_pct=decision.used_pct,
            email_ok=sent,
        ).info("budget alert tick — crossed threshold")
    return {"sent": sent, "used_pct": decision.used_pct}
