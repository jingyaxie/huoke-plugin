#!/usr/bin/env python3
"""Repair legacy local DB state before alembic upgrade (squashed migrations)."""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, inspect, text


def _engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    return create_engine(url)


def _column_names(inspector, table: str) -> set[str]:
    return {col["name"] for col in inspector.get_columns(table)}


def _index_names(inspector, table: str) -> set[str]:
    return {idx["name"] for idx in inspector.get_indexes(table)}


def repair() -> None:
    engine = _engine()
    inspector = inspect(engine)

    with engine.begin() as conn:
        tables = set(inspector.get_table_names())
        if "alembic_version" not in tables:
            if tables.intersection({"authors", "videos", "comments"}):
                print("[db-repair] init.sql 已建表但无 alembic_version，stamp 0001_initial", file=sys.stderr)
                conn.execute(
                    text(
                        "CREATE TABLE alembic_version ("
                        "version_num VARCHAR(32) NOT NULL, "
                        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
                        ")"
                    )
                )
                conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0001_initial')"))
            return

        current = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
        known_heads = {"0001_initial", "0002_interaction_logs"}
        if current and current not in known_heads and tables.intersection({"authors", "videos"}):
            print(f"[db-repair] stamping alembic_version: {current} -> 0001_initial", file=sys.stderr)
            conn.execute(text("UPDATE alembic_version SET version_num = '0001_initial'"))
            current = "0001_initial"

        if "interaction_logs" in tables and current != "0002_interaction_logs":
            print(
                "[db-repair] interaction_logs 已存在，stamp alembic_version -> 0002_interaction_logs",
                file=sys.stderr,
            )
            conn.execute(text("UPDATE alembic_version SET version_num = '0002_interaction_logs'"))

        if "authors" in tables:
            author_cols = _column_names(inspector, "authors")
            author_indexes = _index_names(inspector, "authors")
            if "douyin_user_id" in author_cols and "platform_user_id" not in author_cols:
                print("[db-repair] rename authors.douyin_user_id -> platform_user_id", file=sys.stderr)
                if "uq_authors_tenant_platform_user" in author_indexes:
                    conn.execute(text("ALTER TABLE authors DROP INDEX uq_authors_tenant_platform_user"))
                if "ix_authors_douyin_user_id" in author_indexes:
                    conn.execute(text("ALTER TABLE authors DROP INDEX ix_authors_douyin_user_id"))
                conn.execute(
                    text(
                        "ALTER TABLE authors CHANGE douyin_user_id platform_user_id "
                        "VARCHAR(64) NULL"
                    )
                )
                conn.execute(
                    text(
                        "ALTER TABLE authors ADD UNIQUE KEY uq_authors_tenant_platform_user "
                        "(tenant_id, platform, platform_user_id)"
                    )
                )
                conn.execute(text("ALTER TABLE authors ADD INDEX ix_authors_platform_user_id (platform_user_id)"))

        if "videos" in tables:
            video_cols = _column_names(inspector, "videos")
            video_indexes = _index_names(inspector, "videos")
            if "douyin_video_id" in video_cols:
                print("[db-repair] migrate videos.douyin_video_id -> external_id", file=sys.stderr)
                conn.execute(
                    text(
                        "UPDATE videos SET external_id = douyin_video_id "
                        "WHERE (external_id IS NULL OR external_id = '') "
                        "AND douyin_video_id IS NOT NULL"
                    )
                )
                if "uq_videos_tenant_platform_video" in video_indexes:
                    conn.execute(text("ALTER TABLE videos DROP INDEX uq_videos_tenant_platform_video"))
                if "ix_videos_douyin_video_id" in video_indexes:
                    conn.execute(text("ALTER TABLE videos DROP INDEX ix_videos_douyin_video_id"))
                conn.execute(text("ALTER TABLE videos DROP COLUMN douyin_video_id"))
                if "uq_videos_tenant_platform_external" not in _index_names(inspector, "videos"):
                    conn.execute(
                        text(
                            "ALTER TABLE videos ADD UNIQUE KEY uq_videos_tenant_platform_external "
                            "(tenant_id, platform, external_id)"
                        )
                    )


if __name__ == "__main__":
    repair()
