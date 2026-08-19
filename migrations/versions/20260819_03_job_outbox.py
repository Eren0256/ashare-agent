"""Add a transactional outbox for Redis job dispatch.

Revision ID: 20260819_03
Revises: 20260819_02
Create Date: 2026-08-19
"""

from alembic import op
import sqlalchemy as sa

revision = "20260819_03"
down_revision = "20260819_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_outbox",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("broker_message_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index(
        "idx_job_outbox_pending",
        "job_outbox",
        ["created_at"],
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_job_outbox_pending", table_name="job_outbox")
    op.drop_table("job_outbox")
