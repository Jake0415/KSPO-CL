"""stats views — v_stats_overview (materialized) + v_cost_daily (regular)

Revision ID: 0004_stats_views
Revises: 0003_fk_cascade
Create Date: 2026-05-07

M4.T4.3 — 운영 메트릭 집계용 뷰.
- v_stats_overview: 도메인별 INDEXED/DROPPED/ERROR/REMOVED + 총 토큰 (페이지·청크 수가
  많아 매번 집계는 비싸므로 머티리얼라이즈드 — 5분 cron으로 갱신)
- v_cost_daily: llm_usage 일별·모델별·purpose별 비용 합계 (행 수 적어 일반 view OK)

KRW 환산은 view에서 안 함 — 환율 변동 시 환산 시점이 모호. 호출 측이 cost_usd ×
USD_TO_KRW_RATE로 변환.
"""
from __future__ import annotations

from alembic import op

revision = "0004_stats_views"
down_revision = "0003_fk_cascade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE MATERIALIZED VIEW v_stats_overview AS
        SELECT d.id AS domain_id,
               d.host,
               COUNT(p.*) FILTER (WHERE p.status='INDEXED')        AS indexed,
               COUNT(p.*) FILTER (WHERE p.status='DROPPED')        AS dropped,
               COUNT(p.*) FILTER (WHERE p.status='ERROR')          AS errors,
               COUNT(p.*) FILTER (WHERE p.status='REMOVED')        AS removed,
               COALESCE(SUM(c.token_len), 0)                       AS total_tokens
          FROM domains d
          LEFT JOIN pages  p ON p.domain_id = d.id
          LEFT JOIN chunks c ON c.page_id   = p.id
         GROUP BY d.id, d.host;
        """
    )
    # UNIQUE INDEX 필수 — REFRESH MATERIALIZED VIEW CONCURRENTLY 활성화용.
    op.execute(
        "CREATE UNIQUE INDEX idx_v_stats_overview_domain "
        "ON v_stats_overview(domain_id);"
    )

    op.execute(
        """
        CREATE VIEW v_cost_daily AS
        SELECT date_trunc('day', created_at) AS day,
               model,
               purpose,
               SUM(cost_usd) AS cost_usd
          FROM llm_usage
         GROUP BY 1, 2, 3
         ORDER BY 1 DESC;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_cost_daily;")
    op.execute("DROP INDEX IF EXISTS idx_v_stats_overview_domain;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS v_stats_overview;")
