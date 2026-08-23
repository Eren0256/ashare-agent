"""Store portable artifact keys instead of absolute paths.

Revision ID: 20260819_02
Revises: 20260819_01
Create Date: 2026-08-19
"""

from alembic import op

revision = "20260819_02"
down_revision = "20260819_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("artifacts", "file_path", new_column_name="storage_key")


def downgrade() -> None:
    op.alter_column("artifacts", "storage_key", new_column_name="file_path")
