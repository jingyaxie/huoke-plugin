"""task compile snapshot columns

Revision ID: 0004_task_compile_snapshot
Revises: 0003_task_instances
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_task_compile_snapshot"
down_revision = "0003_task_instances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task_instances", sa.Column("raw_payload", sa.JSON(), nullable=True))
    op.add_column("task_instances", sa.Column("compile_plan", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("task_instances", "compile_plan")
    op.drop_column("task_instances", "raw_payload")
