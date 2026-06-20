"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "authors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("platform", sa.String(length=32), nullable=False, server_default="douyin"),
        sa.Column("platform_user_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("profile_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "platform", "platform_user_id", name="uq_authors_tenant_platform_user"),
    )
    op.create_index("ix_authors_tenant_id", "authors", ["tenant_id"])
    op.create_index("ix_authors_platform", "authors", ["platform"])
    op.create_index("ix_authors_platform_user_id", "authors", ["platform_user_id"])
    op.create_index("ix_authors_name", "authors", ["name"])

    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("platform", sa.String(length=32), nullable=False, server_default="douyin"),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("authors.id"), nullable=True),
        sa.Column("video_url", sa.Text(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("share_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("publish_time", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.UniqueConstraint("tenant_id", "platform", "external_id", name="uq_videos_tenant_platform_external"),
    )
    op.create_index("ix_videos_tenant_id", "videos", ["tenant_id"])
    op.create_index("ix_videos_platform", "videos", ["platform"])
    op.create_index("ix_videos_external_id", "videos", ["external_id"])
    op.create_index("ix_videos_author_id", "videos", ["author_id"])

    op.create_table(
        "hot_rank_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("platform", sa.String(length=32), nullable=False, server_default="douyin"),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id"), nullable=False),
        sa.Column("score", sa.Numeric(18, 6), nullable=True),
        sa.Column("rank_change", sa.Integer(), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "platform", "snapshot_date", "rank", name="uq_tenant_platform_snapshot_rank"
        ),
        sa.UniqueConstraint(
            "tenant_id", "platform", "snapshot_date", "video_id", name="uq_tenant_platform_snapshot_video"
        ),
    )
    op.create_index("ix_hot_rank_snapshots_tenant_id", "hot_rank_snapshots", ["tenant_id"])
    op.create_index("ix_hot_rank_snapshots_platform", "hot_rank_snapshots", ["platform"])
    op.create_index("ix_hot_rank_snapshots_snapshot_date", "hot_rank_snapshots", ["snapshot_date"])
    op.create_index("ix_hot_rank_snapshots_rank", "hot_rank_snapshots", ["rank"])
    op.create_index("ix_hot_rank_snapshots_video_id", "hot_rank_snapshots", ["video_id"])

    op.create_table(
        "daily_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("platform", sa.String(length=32), nullable=False, server_default="douyin"),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="template"),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=True),
        sa.Column("pdf_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "platform", "report_date", name="uq_daily_reports_tenant_platform_date"),
    )
    op.create_index("ix_daily_reports_tenant_id", "daily_reports", ["tenant_id"])
    op.create_index("ix_daily_reports_platform", "daily_reports", ["platform"])
    op.create_index("ix_daily_reports_report_date", "daily_reports", ["report_date"])

    op.create_table(
        "tenant_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("key_hash", name="uq_tenant_api_keys_key_hash"),
    )
    op.create_index("ix_tenant_api_keys_tenant_id", "tenant_api_keys", ["tenant_id"])

    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=128), nullable=True),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
        sa.Column("display_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "crawl_cache_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("cache_key", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("params_hash", sa.String(length=64), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("cache_key", name="uq_crawl_cache_key"),
    )
    op.create_index("ix_crawl_cache_entries_cache_key", "crawl_cache_entries", ["cache_key"])
    op.create_index("ix_crawl_cache_entries_operation", "crawl_cache_entries", ["operation"])
    op.create_index("ix_crawl_cache_entries_tenant_id", "crawl_cache_entries", ["tenant_id"])
    op.create_index("ix_crawl_cache_entries_platform", "crawl_cache_entries", ["platform"])
    op.create_index("ix_crawl_cache_entries_account_id", "crawl_cache_entries", ["account_id"])
    op.create_index("ix_crawl_cache_entries_expires_at", "crawl_cache_entries", ["expires_at"])

    op.create_table(
        "content_comments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("content_id", sa.String(length=128), nullable=False),
        sa.Column("comment_id", sa.String(length=128), nullable=False),
        sa.Column("parent_comment_id", sa.String(length=128), nullable=True),
        sa.Column("nickname", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("comment_text", sa.Text(), nullable=False),
        sa.Column("digg_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("create_time", sa.Integer(), nullable=True),
        sa.Column("content_url", sa.Text(), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "platform",
            "content_id",
            "comment_id",
            name="uq_content_comments",
        ),
    )
    op.create_index("ix_content_comments_tenant_id", "content_comments", ["tenant_id"])
    op.create_index("ix_content_comments_platform", "content_comments", ["platform"])
    op.create_index("ix_content_comments_content_id", "content_comments", ["content_id"])
    op.create_index("ix_content_comments_parent_comment_id", "content_comments", ["parent_comment_id"])


def downgrade() -> None:
    op.drop_table("content_comments")
    op.drop_table("crawl_cache_entries")
    op.drop_table("users")
    op.drop_table("tenants")
    op.drop_table("tenant_api_keys")
    op.drop_table("daily_reports")
    op.drop_table("hot_rank_snapshots")
    op.drop_table("videos")
    op.drop_table("authors")
