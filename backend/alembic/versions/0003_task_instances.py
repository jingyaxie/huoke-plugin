"""task_instances and task_phase_runs

Revision ID: 0003_task_instances
Revises: 0002_interaction_logs
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_task_instances"
down_revision = "0002_interaction_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_instances",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("template_id", sa.String(length=64), nullable=False),
        sa.Column("template_version", sa.String(length=32), nullable=False, server_default="1.0.0"),
        sa.Column("executor_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("current_phase", sa.String(length=64), nullable=True),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("external_ref", sa.String(length=128), nullable=True),
        sa.Column("adapter_id", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="local"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("webhook_url", sa.Text(), nullable=True),
        sa.Column("webhook_headers", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_task_instances_tenant_id", "task_instances", ["tenant_id"])
    op.create_index("ix_task_instances_template_id", "task_instances", ["template_id"])
    op.create_index("ix_task_instances_platform", "task_instances", ["platform"])
    op.create_index("ix_task_instances_status", "task_instances", ["status"])
    op.create_index("ix_task_instances_external_ref", "task_instances", ["external_ref"])
    op.create_index("ix_task_instances_created_at", "task_instances", ["created_at"])
    op.create_index(
        "ix_task_instances_tenant_status_created",
        "task_instances",
        ["tenant_id", "status", "created_at"],
    )

    op.create_table(
        "task_phase_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("phase_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("output_snapshot", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_task_phase_runs_task_id", "task_phase_runs", ["task_id"])
    op.create_index("ix_task_phase_runs_tenant_id", "task_phase_runs", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_task_phase_runs_tenant_id", table_name="task_phase_runs")
    op.drop_index("ix_task_phase_runs_task_id", table_name="task_phase_runs")
    op.drop_table("task_phase_runs")
    op.drop_index("ix_task_instances_tenant_status_created", table_name="task_instances")
    op.drop_index("ix_task_instances_created_at", table_name="task_instances")
    op.drop_index("ix_task_instances_external_ref", table_name="task_instances")
    op.drop_index("ix_task_instances_status", table_name="task_instances")
    op.drop_index("ix_task_instances_platform", table_name="task_instances")
    op.drop_index("ix_task_instances_template_id", table_name="task_instances")
    op.drop_index("ix_task_instances_tenant_id", table_name="task_instances")
    op.drop_table("task_instances")
