"""interaction_logs table

Revision ID: 0002_interaction_logs
Revises: 0001_initial
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_interaction_logs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interaction_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("engine", sa.String(length=64), nullable=False, server_default="agent_skill"),
        sa.Column("comment_id", sa.String(length=128), nullable=True),
        sa.Column("content_id", sa.String(length=128), nullable=True),
        sa.Column("content_url", sa.Text(), nullable=True),
        sa.Column("target_user_id", sa.String(length=128), nullable=True),
        sa.Column("target_sec_uid", sa.String(length=128), nullable=True),
        sa.Column("target_nickname", sa.String(length=255), nullable=True),
        sa.Column("keyword", sa.String(length=255), nullable=True),
        sa.Column("agent_profile_id", sa.String(length=64), nullable=True),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("reply_text", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_interaction_logs_tenant_id", "interaction_logs", ["tenant_id"])
    op.create_index("ix_interaction_logs_platform", "interaction_logs", ["platform"])
    op.create_index("ix_interaction_logs_action", "interaction_logs", ["action"])
    op.create_index("ix_interaction_logs_comment_id", "interaction_logs", ["comment_id"])
    op.create_index("ix_interaction_logs_target_user_id", "interaction_logs", ["target_user_id"])
    op.create_index("ix_interaction_logs_created_at", "interaction_logs", ["created_at"])
    op.create_index(
        "ix_il_tenant_platform_created",
        "interaction_logs",
        ["tenant_id", "platform", "created_at"],
    )
    op.create_index(
        "ix_il_comment_action",
        "interaction_logs",
        ["tenant_id", "platform", "comment_id", "action"],
    )
    op.create_index(
        "ix_il_user_action",
        "interaction_logs",
        ["tenant_id", "platform", "target_user_id", "action"],
    )


def downgrade() -> None:
    op.drop_index("ix_il_user_action", table_name="interaction_logs")
    op.drop_index("ix_il_comment_action", table_name="interaction_logs")
    op.drop_index("ix_il_tenant_platform_created", table_name="interaction_logs")
    op.drop_index("ix_interaction_logs_created_at", table_name="interaction_logs")
    op.drop_index("ix_interaction_logs_target_user_id", table_name="interaction_logs")
    op.drop_index("ix_interaction_logs_comment_id", table_name="interaction_logs")
    op.drop_index("ix_interaction_logs_action", table_name="interaction_logs")
    op.drop_index("ix_interaction_logs_platform", table_name="interaction_logs")
    op.drop_index("ix_interaction_logs_tenant_id", table_name="interaction_logs")
    op.drop_table("interaction_logs")
