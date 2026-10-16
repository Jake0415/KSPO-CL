"""fk cascade — domain 삭제 시 자손 일괄 삭제 + llm_usage 보존 차단 해소

Revision ID: 0003_fk_cascade
Revises: 0002_core_tables
Create Date: 2026-05-07

도메인 삭제(API) 500 에러 원인: pages.domain_id / attachments.domain_id /
crawl_jobs.domain_id가 ondelete=CASCADE 미설정. 페이지 삭제(자손 cascade) 시에도
llm_usage.page_id/attachment_id/job_id가 막아 행이 유지되며 FK 위반 발생.

설계 정책(CLAUDE.md "백업 미운영, 재크롤로 복원")상 도메인 삭제는 자손 통째 삭제가
정상. llm_usage는 누적 비용 분석용이지만 도메인 삭제 시 함께 사라져도 다른 도메인
누적치만으로 분석 가능하므로 CASCADE.
"""
from __future__ import annotations

from alembic import op

revision = "0003_fk_cascade"
down_revision = "0002_core_tables"
branch_labels = None
depends_on = None


# (table, constraint_name, local_col, ref_table, ref_col)
_FK_CASCADES = [
    ("crawl_jobs", "fk_crawl_jobs_domain_id_domains", "domain_id", "domains", "id"),
    ("pages", "fk_pages_domain_id_domains", "domain_id", "domains", "id"),
    ("attachments", "fk_attachments_domain_id_domains", "domain_id", "domains", "id"),
    ("llm_usage", "fk_llm_usage_page_id_pages", "page_id", "pages", "id"),
    ("llm_usage", "fk_llm_usage_attachment_id_attachments", "attachment_id", "attachments", "id"),
    ("llm_usage", "fk_llm_usage_job_id_crawl_jobs", "job_id", "crawl_jobs", "id"),
]


def upgrade() -> None:
    for table, name, col, ref_table, ref_col in _FK_CASCADES:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            name, table, ref_table, [col], [ref_col], ondelete="CASCADE"
        )


def downgrade() -> None:
    for table, name, col, ref_table, ref_col in _FK_CASCADES:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, ref_table, [col], [ref_col])
