"""task auto_restart column

Revision ID: 0006_task_auto_restart
Revises: 0005_task_scheduled_at
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_task_auto_restart"
down_revision = "0005_task_scheduled_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_instances",
        sa.Column("auto_restart", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("task_instances", "auto_restart")
