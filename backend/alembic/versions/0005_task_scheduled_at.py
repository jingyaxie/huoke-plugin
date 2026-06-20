"""task scheduled_at column

Revision ID: 0005_task_scheduled_at
Revises: 0004_task_compile_snapshot
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_task_scheduled_at"
down_revision = "0004_task_compile_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task_instances", sa.Column("scheduled_at", sa.DateTime(), nullable=True))
    op.create_index("ix_task_instances_scheduled_at", "task_instances", ["scheduled_at"])
    op.create_index("ix_task_instances_status_scheduled_at", "task_instances", ["status", "scheduled_at"])


def downgrade() -> None:
    op.drop_index("ix_task_instances_status_scheduled_at", table_name="task_instances")
    op.drop_index("ix_task_instances_scheduled_at", table_name="task_instances")
    op.drop_column("task_instances", "scheduled_at")
